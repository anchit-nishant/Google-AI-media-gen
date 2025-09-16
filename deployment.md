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

#### 2.4 Create OAuth Credentials for User Login

To allow users to sign in with their Google accounts, you must create OAuth 2.0 credentials.

##### 2.4.1 Configure the OAuth Consent Screen

First, configure what users will see when they grant permission to your app.

1.  In the Google Cloud Console, navigate to **APIs & Services > OAuth consent screen**.
2.  Choose **External** for the User Type and click **Create**.
3.  Fill in the required fields:
    -   **App name**: e.g., `AI Media Generator`
    -   **User support email**: Your email address.
    -   **Developer contact information**: Your email address.
4.  Click **Save and Continue**.
5.  On the **Scopes** page, click **Add or Remove Scopes**. Find and add the following three scopes:
    -   `.../auth/userinfo.email`
    -   `.../auth/userinfo.profile`
    -   `openid`
6.  Click **Update**, then **Save and Continue**.
7.  On the **Test users** page, click **Add Users** and enter the Google email addresses you will use for testing while the app is in "Testing" mode.
8.  Click **Save and Continue**, then go back to the dashboard.

##### 2.4.2 Create the OAuth Client ID

1.  In the left menu, go to **APIs & Services > Credentials**.
2.  Click **+ Create Credentials** and select **OAuth client ID**.
3.  Configure the client ID:
    -   **Application type**: Select **Web application**.
    -   **Name**: Give it a name, like `Media Gen Web App`.
    -   **Authorized redirect URIs**: This is a critical step. You must add the URLs where Google can send users after they log in.
        -   For local development, add: `http://localhost:8501`
        -   After deploying to Cloud Run, you must **return to this page** and add the service URL (e.g., `https://your-service-name-....run.app`).
4.  Click **Create**. A pop-up will appear with your **Client ID** and **Client Secret**. Copy both of these values for the next step.

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

#### Google OAuth Credentials

```
GOOGLE_CLIENT_ID="your-client-id-from-oauth-credentials"
GOOGLE_CLIENT_SECRET="your-client-secret-from-oauth-credentials"
REDIRECT_URI="your-cloud-run-url"
```

#### History Tracking

```
DB_ID="your-firestore-db-id"
```

Cloud Build needs access to the .env file. Open the `.gitignore` file and comment out the line `.env` by adding a `#` in front of it: `#.env`.

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

When prompted `Allow unauthenticated invocations...?` , enter `N` to keep the service private and secure.

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
