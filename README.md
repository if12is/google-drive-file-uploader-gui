# Google Drive File Uploader with GUI

A Python GUI application to upload files to Google Drive, with options to set file privacy (public/private) and get a shareable link.

## Features

- Upload files to Google Drive via a simple GUI.
- Choose whether the uploaded file is public or private.
- Get a shareable link if the file is public.

## Setup

1. **Clone the repository:**

   ```
   git clone https://github.com/if12is/google-drive-file-uploader-gui.git
   cd uploud files in google drive with gui interface python code
   ```

2. **Install dependencies:**

   ```
   pip install -r requirements.txt
   ```

3. **Google Drive API Setup:**
   - Go to [Google Cloud Console](https://console.developers.google.com/).
   - Create a project and enable the Google Drive API.
   - Download `credentials.json` and place it in the project root.

## Setup Credentials

This application requires Google OAuth credentials to function:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Google Drive API
4. Create OAuth 2.0 credentials
5. Download the credentials JSON file
6. Rename it to `client_secrets.json` and place it in the project root directory

**IMPORTANT: Never commit your credentials to version control!**

The application will use these credentials to authenticate with Google Drive.

## Usage

Run the main application:

```
python -m src.main
```

## Testing

```
python -m unittest discover tests
```

## Contributing

Pull requests are welcome!

## License

MIT License
