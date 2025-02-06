from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
import pandas as pd
import os
import openai
from collections import defaultdict

app = FastAPI()

# Configure OpenAI with environment variable
openai.api_key = os.environ.get("OPENAI_API_KEY")

# Rate limiting storage
stall_usage = defaultdict(int)
GENERATION_LIMIT = 3

# Update CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://ai-image-generator-five-topaz.vercel.app",  # Your Vercel frontend URL
        "http://localhost:5173",  # Local development URL
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Google Drive API setup
SCOPES = ['https://www.googleapis.com/auth/drive.file']
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_CREDENTIALS")  # Will be set as an environment variable in Render

# Get Drive share emails from environment
DRIVE_SHARE_EMAILS = os.environ.get("DRIVE_SHARE_EMAILS", "").split(",")

try:
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    drive_service = build('drive', 'v3', credentials=credentials)
except Exception as e:
    print(f"Error setting up Google Drive credentials: {e}")

class RegistrationData(BaseModel):
    projectName: str
    stallNo: str

    class Config:
        # Add validation
        json_schema_extra = {
            "example": {
                "projectName": "My Project",
                "stallNo": "A123"
            }
        }

class ImagePrompt(BaseModel):
    prompt: str
    stallNo: str

    class Config:
        # Add validation
        min_length = 1
        max_length = 1000

# After the file creation/update, add sharing permissions
def share_file(file_id, email):
    try:
        permission = {
            'type': 'user',
            'role': 'writer',
            'emailAddress': email
        }
        drive_service.permissions().create(
            fileId=file_id,
            body=permission,
            sendNotificationEmail=False
        ).execute()
        print(f"File shared successfully with {email}")
    except Exception as e:
        print(f"Error sharing file: {e}")

@app.post("/api/register")
async def register_user(data: RegistrationData):
    print(f"Received registration data: {data}")
    
    # Validate input
    if not data.projectName.strip():
        raise HTTPException(
            status_code=422,
            detail="Project name cannot be empty"
        )
    
    if not data.stallNo.strip():
        raise HTTPException(
            status_code=422,
            detail="Stall number cannot be empty"
        )

    try:
        # Check if file exists in Google Drive to verify uniqueness
        file_name = 'Makerfest.csv'
        response = drive_service.files().list(
            q=f"name='{file_name}'",
            spaces='drive',
            fields='files(id, name)'
        ).execute()

        file_id = None

        try:
            if response['files']:
                # File exists, update it
                file_id = response['files'][0]['id']
                
                # Get existing content
                request = drive_service.files().get_media(fileId=file_id)
                existing_content = request.execute()
                existing_df = pd.read_csv(io.StringIO(existing_content.decode('utf-8')))
                
                # Check for duplicate stall number
                if not existing_df.empty and data.stallNo in existing_df['Stall_No'].values:
                    raise HTTPException(
                        status_code=400,
                        detail="This stall number is already registered"
                    )
                
                # Create DataFrame with the new registration
                new_registration = pd.DataFrame([{
                    'Timestamp': datetime.now().isoformat(),
                    'Project_Name': data.projectName,
                    'Stall_No': data.stallNo
                }])
                
                # Append new registration
                updated_df = pd.concat([existing_df, new_registration], ignore_index=True)
                
                # Convert to CSV
                csv_buffer = io.StringIO()
                updated_df.to_csv(csv_buffer, index=False)
                media = MediaIoBaseUpload(
                    io.BytesIO(csv_buffer.getvalue().encode()),
                    mimetype='text/csv',
                    resumable=True
                )
                
                # Update file
                drive_service.files().update(
                    fileId=file_id,
                    media_body=media
                ).execute()
                
                # Share the file with specific email(s)
                if file_id:
                    for email in DRIVE_SHARE_EMAILS:
                        if email.strip():  # Only share if email is not empty
                            share_file(file_id, email.strip())
                    
                    # Get the shareable link
                    file_data = drive_service.files().get(
                        fileId=file_id,
                        fields='webViewLink'
                    ).execute()
                    print(f"File shareable link: {file_data.get('webViewLink')}")

            else:
                # Create new file
                csv_buffer = io.StringIO()
                new_registration.to_csv(csv_buffer, index=False)
                
                file_metadata = {
                    'name': file_name,
                    'mimeType': 'text/csv',
                }
                
                media = MediaIoBaseUpload(
                    io.BytesIO(csv_buffer.getvalue().encode()),
                    mimetype='text/csv',
                    resumable=True
                )
                
                file = drive_service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id'
                ).execute()
                
                file_id = file.get('id')

        except Exception as drive_error:
            print(f"Drive operation error: {str(drive_error)}")
            raise

        return {"success": True, "message": "Registration saved successfully"}

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error during registration: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate-image")
async def generate_image(data: ImagePrompt):
    print(f"Received request with data: {data}")
    
    # Validate input
    if not data.prompt.strip():
        raise HTTPException(
            status_code=422,
            detail="Prompt cannot be empty"
        )
    
    if not data.stallNo.strip():
        raise HTTPException(
            status_code=422,
            detail="Stall number cannot be empty"
        )

    # Check if stall has reached generation limit
    if stall_usage[data.stallNo] >= GENERATION_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"This stall has reached the limit of {GENERATION_LIMIT} image generations for this competition."
        )
    
    try:
        response = openai.images.generate(
            model="dall-e-3",
            prompt=data.prompt.strip(),
            size="1024x1024",
            quality="standard",
            n=1,
        )
        
        image_url = response.data[0].url
        
        # Increment the usage counter for this stall
        stall_usage[data.stallNo] += 1

        # Update the registration in Google Drive with prompt and image URL
        file_name = 'Makerfest.csv'
        response = drive_service.files().list(
            q=f"name='{file_name}'",
            spaces='drive',
            fields='files(id, name)'
        ).execute()

        if response['files']:
            file_id = response['files'][0]['id']
            request = drive_service.files().get_media(fileId=file_id)
            existing_content = request.execute()
            df = pd.read_csv(io.StringIO(existing_content.decode('utf-8')))
            
            # Add new row for this generation
            new_row = pd.DataFrame([{
                'Timestamp': datetime.now().isoformat(),
                'Stall_No': data.stallNo,
                'Prompt': data.prompt,
                'Generated_Image_URL': image_url,
                'Generation_Number': stall_usage[data.stallNo]
            }])
            
            # Append the new row
            updated_df = pd.concat([df, new_row], ignore_index=True)
            
            # Save updated CSV
            csv_buffer = io.StringIO()
            updated_df.to_csv(csv_buffer, index=False)
            media = MediaIoBaseUpload(
                io.BytesIO(csv_buffer.getvalue().encode()),
                mimetype='text/csv',
                resumable=True
            )
            
            drive_service.files().update(
                fileId=file_id,
                media_body=media
            ).execute()

        return {
            "success": True, 
            "imageUrl": image_url,
            "remainingGenerations": GENERATION_LIMIT - stall_usage[data.stallNo]
        }
    except Exception as e:
        print(f"Error generating image: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Add an endpoint to check remaining generations for a stall
@app.get("/check-generation-limit/{stall_no}")
async def check_limit(stall_no: str):
    remaining = max(0, GENERATION_LIMIT - stall_usage[stall_no])
    return {
        "remaining_generations": remaining,
        "total_generations": GENERATION_LIMIT,
        "used_generations": stall_usage[stall_no]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
