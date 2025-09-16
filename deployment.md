# End-to-End Deployment Guide

Follow these steps carefully to configure your Google Cloud environment and deploy the application.

## Part 1: Google Cloud Project Setup

Before deploying, you must prepare your Google Cloud project by enabling the necessary APIs and creating a service account with the correct permissions.

### 1.1 Enable Required APIs

Navigate to the APIs & Services > Library page in the Google Cloud Console and enable the following APIs for your project:

  - Vertex AI API

  - Gemini API

  - Cloud Run Admin API

  - Cloud Build API

  - Artifact Registry API

  - Cloud Datastore API (Firestore)

### 1.2 Create and Configure a Service Account

The application runs using a service account's identity. You need to create one and grant it the appropriate permissions.

1. Go to IAM & Admin > Service Accounts.

2. Click Create Service Account. Give it a name (e.g., cloud-run-media-gen-sa) and an ID.

3. Grant the following IAM roles to the service account:

    - Cloud Run Admin

    - Artifact Registry Writer

    - Cloud Build Editor

    - Cloud Datastore User

    - Service Account User

    - Logs Writer

    - Logs Viewer

    - Vertex AI User

    - Storage Object Creator

Take note of the service account's email address.

## Part 2: Infrastructure Configuration

Next, create the necessary database and storage resources.

#### 2.1 Create a Firestore Database

- In the Cloud Console search bar, look for Firestore.

- Click Create Database.

- Select Native Mode and choose a location (e.g., us-central1).

- Provide a Database ID or use (default).

- Click Create. Remember this Database ID for the .env file.

#### 2.2 Create a Cloud Storage Bucket

- Navigate to Cloud Storage > Buckets and click Create.

- Give the bucket a globally unique name.

- Set the Location type to Region and select us-central-1.

- Crucially, ensure "Enforce public access prevention" is checked.

- Click Create. Remember this bucket name for the .env file.

#### 2.3 Get a Gemini API Key

- Navigate to Google AI Studio.

- Ensure you have selected the correct Google Cloud project.

- Click "Get API key" from the left menu, then "Create API key".

- Copy the generated key and save it securely.

## Part 3: Code and Deployment

Now you will configure the source code and deploy it using a single gcloud command.

#### 3.1 Clone and Configure the Repository

1. Open the Google Cloud Shell or your local terminal.

2. Clone the repository:

3. git clone [https://github.com/anchit-nishant/Google-AI-media-gen](https://github.com/anchit-nishant/Google-AI-media-gen)
cd Google-AI-media-gen

4. Create an environment file from the example:

    ```
    cp env.example .env
    ```

5. Edit the .env file and populate it with your specific values:

#### Google Cloud Configuration

```
PROJECT_ID=your-gcp-project-id
STORAGE_URI=gs://your-bucket-name/
```

#### Gemini Configuration

```
GEMINI_PROJECT_ID=your-gcp-project-id
GEMINI_LOCATION=us-central1
GEMINI_MODEL_NAME=gemini-2.5-pro
GEMINI_API_KEY=your-gemini-api-key-from-ai-studio
```

#### History Tracking

```
DB_ID="your-firestore-db-id"
```

Cloud Build needs access to the .env file. Open the .gitignore file and comment out the line .env by adding a # in front of it: #.env.

#### 3.2 Deploy to Cloud Run
From the root of the project directory, run the following command. Remember to replace the placeholder values.

```
gcloud beta run deploy <service-name> \
  --source . \
  --region us-central1 \
  --service-account <your-service-account-email> \
  --iap \
  --memory 2Gi \
  --cpu 2 \
  --timeout 3600 \
  --project <your-gcp-project-id>
```

When prompted Allow unauthenticated invocations...?, enter n to keep the service private and secure.

## Part 4: Finalizing Access Control

Once deployed, you must grant specific users permission to access the application through the Identity-Aware Proxy (IAP).

- In the Cloud Console, go to Cloud Run and click on your new service.

- Navigate to the Security tab.

- You should see that Identity-Aware Proxy is enabled. Click "Edit Policy".

- Click "Add Principal" and enter the email addresses of users or Google Groups you want to grant access.

- Assign them the IAP-secured Web App User role.

- Click Save.

Users can now access the application URL provided on the Cloud Run service details page.

(Optional) Performance Tuning
If you find that media processing tasks are slow, you can redeploy the service with more CPU resources.

```
gcloud beta run deploy <service-name> \
  --source . \
  --region us-central1 \
  --service-account <your-service-account-email> \
  --iap \
  --memory 2Gi \
  --cpu 4 \
  --timeout 3600 \
  --project <your-gcp-project-id>
```
