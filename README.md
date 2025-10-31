# Databricks API Explorer

A Flask web application that provides SSO authentication to Databricks workspaces and allows you to interact with Databricks APIs through a user-friendly web interface.

## Features

- **SSO Authentication**: Secure authentication to Databricks workspaces using external browser SSO
- **API Explorer**: Interactive interface to call various Databricks APIs (Clusters, Jobs, Workspace, SQL Warehouses, Users)
- **Real-time Logging**: View all authentication and API call logs in real-time
- **Auto-scrolling Log Viewer**: Log viewer automatically scrolls to show the latest messages
- **Log Management**: Clear logs functionality with confirmation

## Prerequisites

- Python 3.8 or higher
- Databricks workspace access
- Valid Databricks account with SSO enabled

## Installation

1. Clone or navigate to the project directory:
```bash
cd databricks-api-explorer
```

2. Create a virtual environment (recommended):
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

The default workspace URL is set to `https://adb-984752964297111.11.azuredatabricks.net`. You can change this in the `app.py` file or enter a different workspace URL during login.

### Environment Variables (Optional)

- `FLASK_SECRET_KEY`: Secret key for Flask sessions (defaults to a dev key)
- `FLASK_HOST`: Host to bind to (defaults to `0.0.0.0`)
- `FLASK_PORT`: Port to run on (defaults to `5000`)

## Running the Application

1. Start the Flask application:
```bash
python app.py
```

2. Open your web browser and navigate to:
```
http://localhost:5000
```

3. Enter your Databricks workspace URL (or use the default) and click "Authenticate with SSO"

4. Complete the SSO authentication in the browser window that opens

5. Once authenticated, you can start exploring Databricks APIs!

## Usage

### Authentication

1. On the login page, enter your Databricks workspace URL
2. Click "Authenticate with SSO"
3. Complete the SSO flow in the browser window
4. You'll be redirected to the main dashboard upon successful authentication

### API Explorer

1. Select a **Category** (Clusters, Jobs, Workspace, SQL Warehouses, Users, Current User)
2. Select an **Action** (List, Get, etc.)
3. If required, enter parameters (e.g., Cluster ID, Job ID, Path)
4. Click "Call API" to execute the request
5. View the response in the API Response section

### Logs

- **View Logs**: The right sidebar shows real-time logs of all authentication and API activities
- **Auto-scroll**: Logs automatically scroll to show the newest messages
- **Manual Scroll**: You can manually scroll up to view older logs
- **Clear Logs**: Click the "Clear Logs" button to clear all log entries (with confirmation)

## Log Files

All logs are saved to `logs/app.log` in the project directory. The log file contains:
- Timestamp for each entry
- Log level (INFO, DEBUG, ERROR, etc.)
- Category ([AUTH], [API], [SYSTEM])
- Detailed messages and error traces

## Project Structure

```
databricks-api-explorer/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── README.md             # This file
├── logs/                 # Log files directory
│   └── app.log          # Application log file
├── templates/            # HTML templates
│   ├── base.html        # Base template
│   ├── login.html       # Login page
│   └── index.html       # Main dashboard
└── static/              # Static files
    ├── css/
    │   └── style.css    # Custom styles
    └── js/
        └── app.js       # JavaScript utilities
```

## Supported APIs

The application supports the following Databricks API categories:

- **Clusters**: List clusters, get cluster details, list node types
- **Jobs**: List jobs, get job details
- **Workspace**: List workspace items, get item status
- **SQL Warehouses**: List warehouses, get warehouse details
- **Users**: List users, get user details
- **Current User**: Get current authenticated user information

## Security Notes

- The default `FLASK_SECRET_KEY` is for development only. Set a secure secret key in production.
- Sessions are stored server-side and use HTTP-only cookies
- SSO authentication uses Databricks' secure external browser flow
- All API calls are authenticated using the SSO session

## Troubleshooting

### Authentication Issues

- Ensure your Databricks workspace URL is correct
- Verify you have access to the workspace
- Check that SSO is enabled for your workspace
- Review the logs for detailed error messages

### API Call Errors

- Verify you're authenticated (check the top right corner)
- Ensure you have permissions for the API you're trying to call
- Check the logs for detailed error information
- Some APIs may require specific parameters (IDs, paths, etc.)

### Log Issues

- Check that the `logs/` directory exists and is writable
- Review file permissions if logs aren't being written
- Clear logs if the log file becomes too large

## License

This project is provided as-is for demonstration purposes.

## Support

For issues related to:
- **Databricks SDK**: See [Databricks SDK documentation](https://databricks-sdk-py.readthedocs.io/)
- **Flask**: See [Flask documentation](https://flask.palletsprojects.com/)

