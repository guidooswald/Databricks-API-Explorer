"""
Databricks API Explorer - Flask web application for Databricks API access with SSO authentication.
"""

import os
import json
import logging
import traceback
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from databricks.sdk import WorkspaceClient, AccountClient
from databricks.sdk.core import Config
from werkzeug.middleware.proxy_fix import ProxyFix

# Configure Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Use ProxyFix for proper handling behind proxies
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Default workspace URL
DEFAULT_WORKSPACE_URL = "https://adb-984752964297111.11.azuredatabricks.net"

# Ensure logs directory exists
LOGS_DIR = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)

# Set up file logging
LOG_FILE = os.path.join(LOGS_DIR, 'app.log')
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler.setFormatter(file_formatter)

# Set up console logging
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# Configure root logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Disable werkzeug default logging to avoid duplicate logs
logging.getLogger('werkzeug').setLevel(logging.WARNING)


def log_auth_event(event_type: str, message: str, **kwargs):
    """Log authentication events with details."""
    log_msg = f"[AUTH] {event_type}: {message}"
    if kwargs:
        log_msg += f" | Details: {json.dumps(kwargs, default=str)}"
    logger.info(log_msg)


def log_api_call(method: str, endpoint: str, status: str = None, error: str = None, 
                 duration_ms: float = None, response_size: int = None, result_count: int = None,
                 user_email: str = None, workspace_url: str = None, **kwargs):
    """Log API calls with comprehensive details."""
    log_msg = f"[API] {method} {endpoint}"
    
    # Add status
    if status:
        log_msg += f" | Status: {status}"
    
    # Add user info if available
    if user_email:
        log_msg += f" | User: {user_email}"
    
    # Add workspace URL if available
    if workspace_url:
        log_msg += f" | Workspace: {workspace_url}"
    
    # Add duration
    if duration_ms is not None:
        log_msg += f" | Duration: {duration_ms:.2f}ms ({duration_ms/1000:.2f}s)"
    
    # Add response size
    if response_size is not None:
        if response_size < 1024:
            log_msg += f" | Response Size: {response_size}B"
        elif response_size < 1024 * 1024:
            log_msg += f" | Response Size: {response_size/1024:.2f}KB"
        else:
            log_msg += f" | Response Size: {response_size/(1024*1024):.2f}MB"
    
    # Add result count for list operations
    if result_count is not None:
        log_msg += f" | Result Count: {result_count}"
    
    # Add error if present
    if error:
        log_msg += f" | Error: {error}"
    
    # Add other details
    if kwargs:
        # Filter out large data that might clutter logs
        filtered_kwargs = {}
        for key, value in kwargs.items():
            if key in ['traceback', 'request_data']:
                # Include traceback and request_data as they're useful
                filtered_kwargs[key] = value
            elif isinstance(value, (dict, list)):
                # Include summary for large structures
                if isinstance(value, list):
                    filtered_kwargs[key] = f"List[{len(value)} items]"
                else:
                    filtered_kwargs[key] = f"Dict[{len(value)} keys]"
            else:
                filtered_kwargs[key] = value
        log_msg += f" | Details: {json.dumps(filtered_kwargs, default=str)}"
    
    logger.info(log_msg)


@app.route('/')
def index():
    """Main page - redirects to login if not authenticated."""
    if 'authenticated' not in session or not session['authenticated']:
        return redirect(url_for('login'))
    return render_template('index.html', workspace_url=session.get('workspace_url', DEFAULT_WORKSPACE_URL))


@app.route('/login')
def login():
    """Login page with SSO authentication."""
    workspace_url = request.args.get('workspace_url', DEFAULT_WORKSPACE_URL)
    
    # If already authenticated, redirect to main page
    if 'authenticated' in session and session['authenticated']:
        return redirect(url_for('index'))
    
    return render_template('login.html', workspace_url=workspace_url, default_workspace=DEFAULT_WORKSPACE_URL)


@app.route('/auth/sso', methods=['POST'])
def auth_sso():
    """Initiate SSO authentication."""
    try:
        workspace_url = request.json.get('workspace_url', DEFAULT_WORKSPACE_URL).strip()
        if not workspace_url:
            workspace_url = DEFAULT_WORKSPACE_URL
        
        log_auth_event("SSO_INITIATE", f"Starting SSO authentication", workspace_url=workspace_url)
        
        # Store workspace URL in session for callback
        session['workspace_url'] = workspace_url
        session['sso_in_progress'] = True
        
        # Initialize Databricks client with SSO
        config = Config(host=workspace_url, auth_type='external-browser')
        client = WorkspaceClient(config=config)
        
        # Test connection by getting current user
        current_user = client.current_user.me()
        
        # Authentication successful
        session['authenticated'] = True
        session['workspace_url'] = workspace_url
        session['user_email'] = current_user.user_name if hasattr(current_user, 'user_name') else 'Unknown'
        session['sso_in_progress'] = False
        
        log_auth_event("SSO_SUCCESS", f"SSO authentication successful", 
                      workspace_url=workspace_url, user=session['user_email'])
        
        return jsonify({
            'success': True,
            'message': 'Authentication successful',
            'user': session['user_email'],
            'workspace_url': workspace_url
        })
    
    except Exception as e:
        session['sso_in_progress'] = False
        error_msg = str(e)
        log_auth_event("SSO_ERROR", f"SSO authentication failed", 
                      workspace_url=workspace_url, error=error_msg, traceback=traceback.format_exc())
        
        return jsonify({
            'success': False,
            'error': error_msg
        }), 400


@app.route('/auth/logout', methods=['POST'])
def logout():
    """Logout and clear session."""
    logout_start_time = datetime.now()
    user_email = session.get('user_email', 'Unknown') if 'authenticated' in session else None
    
    if 'authenticated' in session:
        log_auth_event("LOGOUT_INITIATED", f"User logout initiated", 
                      user=user_email, timestamp=logout_start_time.isoformat())
    
    session.clear()
    logout_duration = (datetime.now() - logout_start_time).total_seconds() * 1000
    
    log_auth_event("LOGOUT_SUCCESS", f"User logged out successfully", 
                  user=user_email, duration_ms=logout_duration)
    
    return jsonify({'success': True, 'message': 'Logged out successfully'})


@app.route('/api/client')
def get_client():
    """Get authenticated Databricks client."""
    if 'authenticated' not in session or not session['authenticated']:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        workspace_url = session.get('workspace_url', DEFAULT_WORKSPACE_URL)
        config = Config(host=workspace_url, auth_type='external-browser')
        client = WorkspaceClient(config=config)
        return client
    except Exception as e:
        log_api_call("GET_CLIENT", "/api/client", error=str(e))
        return None


@app.route('/api/<category>/<action>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def api_call(category, action):
    """Generic endpoint for calling Databricks APIs with configurable timeout."""
    if 'authenticated' not in session or not session['authenticated']:
        return jsonify({'error': 'Not authenticated'}), 401
    
    # Get timeout from request (default 35 seconds)
    timeout = 35
    if request.method == 'GET':
        timeout = int(request.args.get('timeout', 35))
    else:
        try:
            request_data = request.json if request.is_json and request.data else {}
            timeout = int(request_data.get('timeout', 35))
        except (ValueError, TypeError, AttributeError):
            timeout = 35
    
    # Ensure timeout is reasonable (between 1 and 300 seconds)
    timeout = max(1, min(300, timeout))
    
    # Track timing
    api_start_time = datetime.now()
    execution_start_time = None
    
    try:
        workspace_url = session.get('workspace_url', DEFAULT_WORKSPACE_URL)
        user_email = session.get('user_email', 'Unknown')
        
        # Log API call initiation with detailed request info
        log_api_call(
            request.method, 
            f"/api/{category}/{action}",
            status="INITIATED",
            user_email=user_email,
            workspace_url=workspace_url,
            timeout=timeout,
            category=category,
            action=action
        )
        
        config = Config(host=workspace_url, auth_type='external-browser')
        client = WorkspaceClient(config=config)
        
        # Get request data - handle GET vs POST/PUT/DELETE differently
        if request.method == 'GET':
            request_data = request.args.to_dict()
            # Remove timeout from request_data as it's handled separately
            request_data.pop('timeout', None)
        else:
            # For POST/PUT/DELETE, try to get JSON data
            try:
                request_data = request.json if request.is_json and request.data else {}
                # Remove timeout from request_data as it's handled separately
                if isinstance(request_data, dict):
                    request_data.pop('timeout', None)
            except Exception:
                request_data = {}
        
        # Log request parameters
        if request_data:
            log_api_call(
                request.method,
                f"/api/{category}/{action}",
                status="REQUEST_PARAMS",
                user_email=user_email,
                workspace_url=workspace_url,
                request_params=request_data
            )
        
        # Execute API call with timeout using threading
        result_container = {}
        exception_container = {}
        execution_start_time = datetime.now()
        
        def execute_api():
            """Execute the API call in a separate thread."""
            try:
                result = None
                
                # Comprehensive API patterns - all available Databricks API actions
                if category.lower() == 'clusters':
                    if action == 'list':
                        # Set default limit to 100 to prevent timeouts
                        max_items = request_data.get('max_items', 100)
                        max_items = int(max_items) if max_items else 100
                        
                        logger.info(f"Listing clusters with max_items limit: {max_items}")
                        clusters_iterator = client.clusters.list()
                        result = []
                        item_count = 0
                        
                        try:
                            for cluster in clusters_iterator:
                                result.append(cluster)
                                item_count += 1
                                if item_count >= max_items:
                                    logger.info(f"Stopped at {item_count} clusters due to max_items limit")
                                    break
                        except Exception as list_error:
                            logger.error(f"Error iterating clusters list: {list_error}")
                            if result:
                                logger.warning(f"Returning partial results: {len(result)} clusters retrieved before error")
                            else:
                                raise
                    elif action == 'list-node-types':
                        result = list(client.clusters.list_node_types())
                    elif action == 'get':
                        cluster_id = request_data.get('cluster_id')
                        if cluster_id:
                            result = client.clusters.get(cluster_id=cluster_id)
                    elif action == 'start':
                        cluster_id = request_data.get('cluster_id')
                        if cluster_id:
                            result = client.clusters.start(cluster_id=cluster_id)
                    elif action == 'restart':
                        cluster_id = request_data.get('cluster_id')
                        if cluster_id:
                            result = client.clusters.restart(cluster_id=cluster_id)
                    elif action == 'delete':
                        cluster_id = request_data.get('cluster_id')
                        if cluster_id:
                            result = client.clusters.delete(cluster_id=cluster_id)
                    elif action == 'create':
                        # Create cluster - requires cluster configuration
                        cluster_config = request_data.get('cluster_config', {})
                        if cluster_config:
                            result = client.clusters.create(**cluster_config)
                
                elif category.lower() == 'jobs':
                    if action == 'list':
                        # Jobs API uses pagination - explicitly iterate through pages
                        # Set default limit to 100 to prevent timeouts (can be overridden via max_items)
                        max_items = request_data.get('max_items', 100)  # Default to 100 if not specified
                        max_items = int(max_items) if max_items else 100
                        
                        logger.info(f"Listing jobs with max_items limit: {max_items}")
                        jobs_iterator = client.jobs.list()
                        result = []
                        item_count = 0
                        
                        try:
                            for job in jobs_iterator:
                                result.append(job)
                                item_count += 1
                                # Always respect max_items limit to prevent timeouts
                                if item_count >= max_items:
                                    logger.info(f"Stopped at {item_count} jobs due to max_items limit")
                                    break
                        except Exception as list_error:
                            logger.error(f"Error iterating jobs list: {list_error}")
                            # If we got some results before error, return them
                            if result:
                                logger.warning(f"Returning partial results: {len(result)} jobs retrieved before error")
                            else:
                                raise
                    elif action == 'get':
                        job_id = request_data.get('job_id')
                        if job_id:
                            result = client.jobs.get(job_id=int(job_id))
                    elif action == 'run-now':
                        job_id = request_data.get('job_id')
                        if job_id:
                            run_params = request_data.get('run_params', {})
                            result = client.jobs.run_now(job_id=int(job_id), **run_params)
                    elif action == 'delete':
                        job_id = request_data.get('job_id')
                        if job_id:
                            result = client.jobs.delete(job_id=int(job_id))
                    elif action == 'create':
                        job_config = request_data.get('job_config', {})
                        if job_config:
                            result = client.jobs.create(**job_config)
                    elif action == 'update':
                        job_id = request_data.get('job_id')
                        job_config = request_data.get('job_config', {})
                        if job_id and job_config:
                            result = client.jobs.update(job_id=int(job_id), **job_config)
                
                elif category.lower() == 'workspace':
                    if action == 'list':
                        path = request_data.get('path', '/')
                        result = list(client.workspace.list(path=path))
                    elif action == 'get-status':
                        path = request_data.get('path')
                        if path:
                            result = client.workspace.get_status(path=path)
                    elif action == 'get':
                        path = request_data.get('path')
                        format_type = request_data.get('format', 'SOURCE')
                        if path:
                            result = client.workspace.get(path=path, format=format_type)
                    elif action == 'mkdirs':
                        path = request_data.get('path')
                        if path:
                            result = client.workspace.mkdirs(path=path)
                    elif action == 'delete':
                        path = request_data.get('path')
                        recursive = request_data.get('recursive', False)
                        if path:
                            result = client.workspace.delete(path=path, recursive=recursive)
                    elif action == 'import':
                        path = request_data.get('path')
                        content = request_data.get('content')
                        format_type = request_data.get('format', 'SOURCE')
                        language = request_data.get('language')
                        overwrite = request_data.get('overwrite', False)
                        if path and content:
                            result = client.workspace.import_(path=path, content=content, 
                                                              format=format_type, language=language, 
                                                              overwrite=overwrite)
                    elif action == 'export':
                        path = request_data.get('path')
                        format_type = request_data.get('format', 'SOURCE')
                        if path:
                            result = client.workspace.export(path=path, format=format_type)
                
                elif category.lower() == 'sql' or category.lower() == 'warehouses':
                    if action == 'list' or action == 'list-warehouses':
                        # Set default limit to 100 to prevent timeouts
                        max_items = request_data.get('max_items', 100)
                        max_items = int(max_items) if max_items else 100
                        
                        logger.info(f"Listing warehouses with max_items limit: {max_items}")
                        warehouses_iterator = client.warehouses.list()
                        result = []
                        item_count = 0
                        
                        try:
                            for warehouse in warehouses_iterator:
                                result.append(warehouse)
                                item_count += 1
                                if item_count >= max_items:
                                    logger.info(f"Stopped at {item_count} warehouses due to max_items limit")
                                    break
                        except Exception as list_error:
                            logger.error(f"Error iterating warehouses list: {list_error}")
                            if result:
                                logger.warning(f"Returning partial results: {len(result)} warehouses retrieved before error")
                            else:
                                raise
                    elif action == 'get' or action == 'get-warehouse':
                        warehouse_id = request_data.get('warehouse_id') or request_data.get('id')
                        if warehouse_id:
                            result = client.warehouses.get(id=warehouse_id)
                    elif action == 'start':
                        warehouse_id = request_data.get('warehouse_id') or request_data.get('id')
                        if warehouse_id:
                            result = client.warehouses.start(id=warehouse_id)
                    elif action == 'stop':
                        warehouse_id = request_data.get('warehouse_id') or request_data.get('id')
                        if warehouse_id:
                            result = client.warehouses.stop(id=warehouse_id)
                    elif action == 'create':
                        warehouse_config = request_data.get('warehouse_config', {})
                        if warehouse_config:
                            result = client.warehouses.create(**warehouse_config)
                    elif action == 'update':
                        warehouse_id = request_data.get('warehouse_id') or request_data.get('id')
                        warehouse_config = request_data.get('warehouse_config', {})
                        if warehouse_id and warehouse_config:
                            result = client.warehouses.edit(id=warehouse_id, **warehouse_config)
                    elif action == 'delete':
                        warehouse_id = request_data.get('warehouse_id') or request_data.get('id')
                        if warehouse_id:
                            result = client.warehouses.delete(id=warehouse_id)
                
                elif category.lower() == 'users':
                    if action == 'list':
                        # Set default limit to 100 to prevent timeouts
                        max_items = request_data.get('max_items', 100)
                        max_items = int(max_items) if max_items else 100
                        
                        logger.info(f"Listing users with max_items limit: {max_items}")
                        users_iterator = client.users.list()
                        result = []
                        item_count = 0
                        
                        try:
                            for user in users_iterator:
                                result.append(user)
                                item_count += 1
                                if item_count >= max_items:
                                    logger.info(f"Stopped at {item_count} users due to max_items limit")
                                    break
                        except Exception as list_error:
                            logger.error(f"Error iterating users list: {list_error}")
                            if result:
                                logger.warning(f"Returning partial results: {len(result)} users retrieved before error")
                            else:
                                raise
                    elif action == 'get':
                        user_id = request_data.get('user_id') or request_data.get('id')
                        if user_id:
                            result = client.users.get(id=user_id)
                    elif action == 'create':
                        user_config = request_data.get('user_config', {})
                        if user_config:
                            result = client.users.create(**user_config)
                    elif action == 'update':
                        user_id = request_data.get('user_id') or request_data.get('id')
                        user_config = request_data.get('user_config', {})
                        if user_id and user_config:
                            result = client.users.patch(id=user_id, **user_config)
                    elif action == 'delete':
                        user_id = request_data.get('user_id') or request_data.get('id')
                        if user_id:
                            result = client.users.delete(id=user_id)
                
                elif category.lower() == 'groups':
                    if action == 'list':
                        # Groups API may also use pagination - handle explicitly
                        # Set default limit to 100 to prevent timeouts
                        max_items = request_data.get('max_items', 100)
                        max_items = int(max_items) if max_items else 100
                        
                        logger.info(f"Listing groups with max_items limit: {max_items}")
                        groups_iterator = client.groups.list()
                        result = []
                        item_count = 0
                        
                        try:
                            for group in groups_iterator:
                                result.append(group)
                                item_count += 1
                                if item_count >= max_items:
                                    logger.info(f"Stopped at {item_count} groups due to max_items limit")
                                    break
                        except Exception as list_error:
                            logger.error(f"Error iterating groups list: {list_error}")
                            if result:
                                logger.warning(f"Returning partial results: {len(result)} groups retrieved before error")
                            else:
                                raise
                    elif action == 'get':
                        group_id = request_data.get('group_id') or request_data.get('id')
                        if group_id:
                            result = client.groups.get(id=group_id)
                    elif action == 'create':
                        group_config = request_data.get('group_config', {})
                        if group_config:
                            result = client.groups.create(**group_config)
                    elif action == 'update':
                        group_id = request_data.get('group_id') or request_data.get('id')
                        group_config = request_data.get('group_config', {})
                        if group_id and group_config:
                            result = client.groups.patch(id=group_id, **group_config)
                    elif action == 'delete':
                        group_id = request_data.get('group_id') or request_data.get('id')
                        if group_id:
                            result = client.groups.delete(id=group_id)
                
                elif category.lower() == 'pipelines':
                    if action == 'list':
                        # Set default limit to 100 to prevent timeouts
                        max_items = request_data.get('max_items', 100)
                        max_items = int(max_items) if max_items else 100
                        
                        logger.info(f"Listing pipelines with max_items limit: {max_items}")
                        pipelines_iterator = client.pipelines.list_pipelines()
                        result = []
                        item_count = 0
                        
                        try:
                            for pipeline in pipelines_iterator:
                                result.append(pipeline)
                                item_count += 1
                                if item_count >= max_items:
                                    logger.info(f"Stopped at {item_count} pipelines due to max_items limit")
                                    break
                        except Exception as list_error:
                            logger.error(f"Error iterating pipelines list: {list_error}")
                            if result:
                                logger.warning(f"Returning partial results: {len(result)} pipelines retrieved before error")
                            else:
                                raise
                    elif action == 'get':
                        pipeline_id = request_data.get('pipeline_id')
                        if pipeline_id:
                            result = client.pipelines.get(pipeline_id=pipeline_id)
                    elif action == 'start':
                        pipeline_id = request_data.get('pipeline_id')
                        if pipeline_id:
                            result = client.pipelines.start_update(pipeline_id=pipeline_id)
                    elif action == 'stop':
                        pipeline_id = request_data.get('pipeline_id')
                        if pipeline_id:
                            result = client.pipelines.stop(pipeline_id=pipeline_id)
                    elif action == 'create':
                        pipeline_config = request_data.get('pipeline_config', {})
                        if pipeline_config:
                            result = client.pipelines.create(**pipeline_config)
                    elif action == 'update':
                        pipeline_id = request_data.get('pipeline_id')
                        pipeline_config = request_data.get('pipeline_config', {})
                        if pipeline_id and pipeline_config:
                            result = client.pipelines.edit(pipeline_id=pipeline_id, **pipeline_config)
                    elif action == 'delete':
                        pipeline_id = request_data.get('pipeline_id')
                        if pipeline_id:
                            result = client.pipelines.delete(pipeline_id=pipeline_id)
                
                elif category.lower() == 'repos':
                    if action == 'list':
                        # Set default limit to 100 to prevent timeouts
                        max_items = request_data.get('max_items', 100)
                        max_items = int(max_items) if max_items else 100
                        
                        logger.info(f"Listing repos with max_items limit: {max_items}")
                        repos_iterator = client.repos.list()
                        result = []
                        item_count = 0
                        
                        try:
                            for repo in repos_iterator:
                                result.append(repo)
                                item_count += 1
                                if item_count >= max_items:
                                    logger.info(f"Stopped at {item_count} repos due to max_items limit")
                                    break
                        except Exception as list_error:
                            logger.error(f"Error iterating repos list: {list_error}")
                            if result:
                                logger.warning(f"Returning partial results: {len(result)} repos retrieved before error")
                            else:
                                raise
                    elif action == 'get':
                        repo_id = request_data.get('repo_id')
                        if repo_id:
                            result = client.repos.get(repo_id=int(repo_id))
                    elif action == 'create':
                        repo_config = request_data.get('repo_config', {})
                        if repo_config:
                            result = client.repos.create(**repo_config)
                    elif action == 'update':
                        repo_id = request_data.get('repo_id')
                        repo_config = request_data.get('repo_config', {})
                        if repo_id and repo_config:
                            result = client.repos.update(repo_id=int(repo_id), **repo_config)
                    elif action == 'delete':
                        repo_id = request_data.get('repo_id')
                        if repo_id:
                            result = client.repos.delete(repo_id=int(repo_id))
                
                elif category.lower() == 'current-user':
                    if action == 'get' or action == 'me':
                        result = client.current_user.me()
                
                elif category.lower() == 'workspaces':
                    if action == 'list':
                        # Use AccountClient for account-level operations
                        # Set default limit to 100 to prevent timeouts
                        max_items = request_data.get('max_items', 100)
                        max_items = int(max_items) if max_items else 100
                        
                        workspace_url = session.get('workspace_url', DEFAULT_WORKSPACE_URL)
                        try:
                            account_config = Config(host=workspace_url, auth_type='external-browser')
                            account_client = AccountClient(config=account_config)
                            
                            logger.info(f"Listing workspaces with max_items limit: {max_items}")
                            workspaces_iterator = account_client.workspaces.list()
                            result = []
                            item_count = 0
                            
                            try:
                                for workspace in workspaces_iterator:
                                    result.append(workspace)
                                    item_count += 1
                                    if item_count >= max_items:
                                        logger.info(f"Stopped at {item_count} workspaces due to max_items limit")
                                        break
                            except Exception as list_error:
                                logger.error(f"Error iterating workspaces list: {list_error}")
                                if result:
                                    logger.warning(f"Returning partial results: {len(result)} workspaces retrieved before error")
                                else:
                                    raise
                        except Exception as account_error:
                            raise Exception(f"Cannot list workspaces: Account-level access required. Error: {str(account_error)}")
                
                elif category.lower() == 'permissions':
                    if action == 'get':
                        request_object_id = request_data.get('request_object_id')
                        request_object_type = request_data.get('request_object_type')
                        if request_object_id and request_object_type:
                            result = client.permissions.get(request_object_id=request_object_id, 
                                                          request_object_type=request_object_type)
                    elif action == 'set' or action == 'update':
                        request_object_id = request_data.get('request_object_id')
                        request_object_type = request_data.get('request_object_type')
                        access_control_list = request_data.get('access_control_list', [])
                        if request_object_id and request_object_type and access_control_list:
                            result = client.permissions.update(request_object_id=request_object_id,
                                                             request_object_type=request_object_type,
                                                             access_control_list=access_control_list)
                
                elif category.lower() == 'notebooks':
                    # Notebooks are accessed via workspace API
                    if action == 'list':
                        path = request_data.get('path', '/')
                        # Set default limit to 100 to prevent timeouts
                        max_items = request_data.get('max_items', 100)
                        max_items = int(max_items) if max_items else 100
                        
                        logger.info(f"Listing notebooks with max_items limit: {max_items}")
                        workspace_iterator = client.workspace.list(path=path)
                        result = []
                        item_count = 0
                        
                        try:
                            for item in workspace_iterator:
                                if hasattr(item, 'object_type') and 'NOTEBOOK' in str(item.object_type):
                                    result.append(item)
                                    item_count += 1
                                    if item_count >= max_items:
                                        logger.info(f"Stopped at {item_count} notebooks due to max_items limit")
                                        break
                        except Exception as list_error:
                            logger.error(f"Error iterating notebooks list: {list_error}")
                            if result:
                                logger.warning(f"Returning partial results: {len(result)} notebooks retrieved before error")
                            else:
                                raise
                    elif action == 'get':
                        path = request_data.get('path')
                        format_type = request_data.get('format', 'SOURCE')
                        if path:
                            result = client.workspace.get(path=path, format=format_type)
                
                elif category.lower() == 'libraries':
                    if action == 'list':
                        cluster_id = request_data.get('cluster_id')
                        if cluster_id:
                            # Set default limit to 100 to prevent timeouts
                            max_items = request_data.get('max_items', 100)
                            max_items = int(max_items) if max_items else 100
                            
                            logger.info(f"Listing libraries with max_items limit: {max_items}")
                            libraries_iterator = client.libraries.list_cluster_status(cluster_id=cluster_id)
                            result = []
                            item_count = 0
                            
                            try:
                                for library in libraries_iterator:
                                    result.append(library)
                                    item_count += 1
                                    if item_count >= max_items:
                                        logger.info(f"Stopped at {item_count} libraries due to max_items limit")
                                        break
                            except Exception as list_error:
                                logger.error(f"Error iterating libraries list: {list_error}")
                                if result:
                                    logger.warning(f"Returning partial results: {len(result)} libraries retrieved before error")
                                else:
                                    raise
                    elif action == 'install':
                        cluster_id = request_data.get('cluster_id')
                        libraries = request_data.get('libraries', [])
                        if cluster_id and libraries:
                            result = client.libraries.install(cluster_id=cluster_id, libraries=libraries)
                    elif action == 'uninstall':
                        cluster_id = request_data.get('cluster_id')
                        libraries = request_data.get('libraries', [])
                        if cluster_id and libraries:
                            result = client.libraries.uninstall(cluster_id=cluster_id, libraries=libraries)
                
                elif category.lower() == 'dbt':
                    if action == 'list-projects':
                        # Set default limit to 100 to prevent timeouts
                        max_items = request_data.get('max_items', 100)
                        max_items = int(max_items) if max_items else 100
                        
                        logger.info(f"Listing DBT projects with max_items limit: {max_items}")
                        projects_iterator = client.dbt.list_projects()
                        result = []
                        item_count = 0
                        
                        try:
                            for project in projects_iterator:
                                result.append(project)
                                item_count += 1
                                if item_count >= max_items:
                                    logger.info(f"Stopped at {item_count} DBT projects due to max_items limit")
                                    break
                        except Exception as list_error:
                            logger.error(f"Error iterating DBT projects list: {list_error}")
                            if result:
                                logger.warning(f"Returning partial results: {len(result)} DBT projects retrieved before error")
                            else:
                                raise
                    elif action == 'get-project':
                        project_id = request_data.get('project_id')
                        if project_id:
                            result = client.dbt.get_project(project_id=project_id)
                
                elif category.lower() == 'secrets':
                    if action == 'list-scopes':
                        # Set default limit to 100 to prevent timeouts
                        max_items = request_data.get('max_items', 100)
                        max_items = int(max_items) if max_items else 100
                        
                        logger.info(f"Listing secret scopes with max_items limit: {max_items}")
                        scopes_iterator = client.secrets.list_scopes()
                        result = []
                        item_count = 0
                        
                        try:
                            for scope in scopes_iterator:
                                result.append(scope)
                                item_count += 1
                                if item_count >= max_items:
                                    logger.info(f"Stopped at {item_count} secret scopes due to max_items limit")
                                    break
                        except Exception as list_error:
                            logger.error(f"Error iterating secret scopes list: {list_error}")
                            if result:
                                logger.warning(f"Returning partial results: {len(result)} secret scopes retrieved before error")
                            else:
                                raise
                    elif action == 'list-secrets':
                        scope = request_data.get('scope')
                        if scope:
                            # Set default limit to 100 to prevent timeouts
                            max_items = request_data.get('max_items', 100)
                            max_items = int(max_items) if max_items else 100
                            
                            logger.info(f"Listing secrets with max_items limit: {max_items}")
                            secrets_iterator = client.secrets.list_secrets(scope=scope)
                            result = []
                            item_count = 0
                            
                            try:
                                for secret in secrets_iterator:
                                    result.append(secret)
                                    item_count += 1
                                    if item_count >= max_items:
                                        logger.info(f"Stopped at {item_count} secrets due to max_items limit")
                                        break
                            except Exception as list_error:
                                logger.error(f"Error iterating secrets list: {list_error}")
                                if result:
                                    logger.warning(f"Returning partial results: {len(result)} secrets retrieved before error")
                                else:
                                    raise
                
                elif category.lower() == 'instance-pools':
                    if action == 'list':
                        # Set default limit to 100 to prevent timeouts
                        max_items = request_data.get('max_items', 100)
                        max_items = int(max_items) if max_items else 100
                        
                        logger.info(f"Listing instance pools with max_items limit: {max_items}")
                        pools_iterator = client.instance_pools.list()
                        result = []
                        item_count = 0
                        
                        try:
                            for pool in pools_iterator:
                                result.append(pool)
                                item_count += 1
                                if item_count >= max_items:
                                    logger.info(f"Stopped at {item_count} instance pools due to max_items limit")
                                    break
                        except Exception as list_error:
                            logger.error(f"Error iterating instance pools list: {list_error}")
                            if result:
                                logger.warning(f"Returning partial results: {len(result)} instance pools retrieved before error")
                            else:
                                raise
                    elif action == 'get':
                        instance_pool_id = request_data.get('instance_pool_id')
                        if instance_pool_id:
                            result = client.instance_pools.get(instance_pool_id=instance_pool_id)
                    elif action == 'create':
                        pool_config = request_data.get('pool_config', {})
                        if pool_config:
                            result = client.instance_pools.create(**pool_config)
                    elif action == 'update':
                        instance_pool_id = request_data.get('instance_pool_id')
                        pool_config = request_data.get('pool_config', {})
                        if instance_pool_id and pool_config:
                            result = client.instance_pools.edit(instance_pool_id=instance_pool_id, **pool_config)
                    elif action == 'delete':
                        instance_pool_id = request_data.get('instance_pool_id')
                        if instance_pool_id:
                            result = client.instance_pools.delete(instance_pool_id=instance_pool_id)
                
                elif category.lower() == 'jobs-runs':
                    if action == 'list':
                        job_id = request_data.get('job_id')
                        # Set default limit to 100 to prevent timeouts
                        max_items = request_data.get('max_items', 100)
                        max_items = int(max_items) if max_items else 100
                        
                        logger.info(f"Listing job runs with max_items limit: {max_items}")
                        runs_iterator = client.jobs.list_runs(job_id=int(job_id)) if job_id else client.jobs.list_runs()
                        result = []
                        item_count = 0
                        
                        try:
                            for run in runs_iterator:
                                result.append(run)
                                item_count += 1
                                if item_count >= max_items:
                                    logger.info(f"Stopped at {item_count} runs due to max_items limit")
                                    break
                        except Exception as list_error:
                            logger.error(f"Error iterating job runs list: {list_error}")
                            if result:
                                logger.warning(f"Returning partial results: {len(result)} runs retrieved before error")
                            else:
                                raise
                    elif action == 'get':
                        run_id = request_data.get('run_id')
                        if run_id:
                            result = client.jobs.get_run(run_id=int(run_id))
                    elif action == 'cancel':
                        run_id = request_data.get('run_id')
                        if run_id:
                            result = client.jobs.cancel_run(run_id=int(run_id))
                    elif action == 'cancel-all':
                        job_id = request_data.get('job_id')
                        if job_id:
                            result = client.jobs.cancel_all_runs(job_id=int(job_id))
                    elif action == 'get-output':
                        run_id = request_data.get('run_id')
                        if run_id:
                            result = client.jobs.get_run_output(run_id=int(run_id))
                
                elif category.lower() == 'cluster-policies':
                    if action == 'list':
                        # Set default limit to 100 to prevent timeouts
                        max_items = request_data.get('max_items', 100)
                        max_items = int(max_items) if max_items else 100
                        
                        logger.info(f"Listing cluster policies with max_items limit: {max_items}")
                        policies_iterator = client.cluster_policies.list()
                        result = []
                        item_count = 0
                        
                        try:
                            for policy in policies_iterator:
                                result.append(policy)
                                item_count += 1
                                if item_count >= max_items:
                                    logger.info(f"Stopped at {item_count} cluster policies due to max_items limit")
                                    break
                        except Exception as list_error:
                            logger.error(f"Error iterating cluster policies list: {list_error}")
                            if result:
                                logger.warning(f"Returning partial results: {len(result)} cluster policies retrieved before error")
                            else:
                                raise
                    elif action == 'get':
                        policy_id = request_data.get('policy_id')
                        if policy_id:
                            result = client.cluster_policies.get(policy_id=policy_id)
                    elif action == 'create':
                        policy_config = request_data.get('policy_config', {})
                        if policy_config:
                            result = client.cluster_policies.create(**policy_config)
                    elif action == 'update':
                        policy_id = request_data.get('policy_id')
                        policy_config = request_data.get('policy_config', {})
                        if policy_id and policy_config:
                            result = client.cluster_policies.edit(policy_id=policy_id, **policy_config)
                    elif action == 'delete':
                        policy_id = request_data.get('policy_id')
                        if policy_id:
                            result = client.cluster_policies.delete(policy_id=policy_id)
                
                # Convert result to dict if it's not already
                # Handle Databricks SDK objects properly
                def serialize_obj(obj):
                    """Recursively serialize Databricks SDK objects to JSON-serializable format."""
                    if obj is None:
                        return None
                    elif isinstance(obj, (str, int, float, bool)):
                        return obj
                    elif isinstance(obj, dict):
                        return {k: serialize_obj(v) for k, v in obj.items()}
                    elif isinstance(obj, (list, tuple)):
                        return [serialize_obj(item) for item in obj]
                    elif hasattr(obj, 'as_dict'):
                        # Databricks SDK objects with as_dict method
                        try:
                            return serialize_obj(obj.as_dict())
                        except Exception:
                            # Fallback to string if as_dict fails
                            return str(obj)
                    elif hasattr(obj, '__dict__'):
                        # Regular objects with __dict__
                        try:
                            return serialize_obj(obj.__dict__)
                        except Exception:
                            return str(obj)
                    elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
                        # Iterables that aren't strings/bytes
                        try:
                            return [serialize_obj(item) for item in obj]
                        except Exception:
                            return str(obj)
                    else:
                        # Fallback to string representation
                        return str(obj)
                
                if result is not None:
                    result = serialize_obj(result)
                
                result_container['result'] = result
            except Exception as e:
                # Log the exception with more details for debugging
                error_details = {
                    'error': str(e),
                    'error_type': type(e).__name__,
                    'category': category,
                    'action': action,
                    'traceback': traceback.format_exc()
                }
                logger.error(f"Exception in API call {category}/{action}: {json.dumps(error_details, default=str)}")
                exception_container['exception'] = e
                exception_container['details'] = error_details
        
        # Run API call in a thread with timeout
        thread = threading.Thread(target=execute_api)
        thread.daemon = True
        thread.start()
        thread.join(timeout=timeout)
        
        execution_end_time = datetime.now()
        execution_duration_ms = (execution_end_time - execution_start_time).total_seconds() * 1000 if execution_start_time else 0
        
        if thread.is_alive():
            # Thread is still running - timeout occurred
            total_duration_ms = (datetime.now() - api_start_time).total_seconds() * 1000
            timeout_msg = f"API call timed out after {timeout} seconds. The operation may still be running on the server."
            log_api_call(
                request.method, 
                f"/api/{category}/{action}",
                status="TIMEOUT",
                error=timeout_msg,
                duration_ms=total_duration_ms,
                user_email=user_email,
                workspace_url=workspace_url,
                timeout=timeout,
                execution_duration_ms=execution_duration_ms
            )
            return jsonify({
                'success': False,
                'error': timeout_msg,
                'timeout': timeout
            }), 504  # 504 Gateway Timeout
        
        if 'exception' in exception_container:
            # An exception occurred during execution
            total_duration_ms = (datetime.now() - api_start_time).total_seconds() * 1000
            error_msg = str(exception_container['exception'])
            log_api_call(
                request.method, 
                f"/api/{category}/{action}",
                status="ERROR",
                error=error_msg,
                duration_ms=total_duration_ms,
                user_email=user_email,
                workspace_url=workspace_url,
                execution_duration_ms=execution_duration_ms,
                traceback=traceback.format_exc()
            )
            return jsonify({
                'success': False,
                'error': error_msg
            }), 500
        
        # Success - calculate response details
        result = result_container.get('result')
        total_duration_ms = (datetime.now() - api_start_time).total_seconds() * 1000
        
        # Ensure result is serializable - if None, use empty list/dict based on context
        if result is None:
            # If it's a list operation, return empty list; otherwise empty dict
            if 'list' in action.lower():
                result = []
            else:
                result = {}
        
        # Calculate response size - try to serialize with better error handling
        try:
            response_json = json.dumps(result, default=str)
        except (TypeError, ValueError) as json_error:
            logger.warning(f"Failed to serialize result for size calculation: {json_error}. Result type: {type(result)}")
            # Try a simpler serialization
            try:
                response_json = json.dumps(result, default=lambda x: str(x))
            except Exception:
                response_json = '{"error": "Failed to serialize response"}'
        
        response_size = len(response_json.encode('utf-8'))
        
        # Calculate result count
        result_count = None
        if isinstance(result, list):
            result_count = len(result)
        elif isinstance(result, dict) and result:
            # For dict results, count keys or items
            result_count = len(result)
        
        # Log successful API call with comprehensive details
        log_api_call(
            request.method,
            f"/api/{category}/{action}",
            status="SUCCESS",
            duration_ms=total_duration_ms,
            response_size=response_size,
            result_count=result_count,
            user_email=user_email,
            workspace_url=workspace_url,
            timeout=timeout,
            execution_duration_ms=execution_duration_ms,
            request_params=request_data if request_data else None
        )
        
        return jsonify({
            'success': True,
            'data': result,
            'timeout': timeout
        })
    
    except Exception as e:
        total_duration_ms = (datetime.now() - api_start_time).total_seconds() * 1000 if 'api_start_time' in locals() else 0
        error_msg = str(e)
        user_email = session.get('user_email', 'Unknown') if 'session' in locals() else 'Unknown'
        workspace_url = session.get('workspace_url', DEFAULT_WORKSPACE_URL) if 'session' in locals() else DEFAULT_WORKSPACE_URL
        
        log_api_call(
            request.method, 
            f"/api/{category}/{action}",
            status="ERROR",
            error=error_msg,
            duration_ms=total_duration_ms,
            user_email=user_email,
            workspace_url=workspace_url,
            traceback=traceback.format_exc()
        )
        
        return jsonify({
            'success': False,
            'error': error_msg
        }), 500


@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Get log entries from the log file."""
    try:
        lines = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        
        # Return last N lines (or all if less than N)
        max_lines = int(request.args.get('max_lines', 1000))
        lines = lines[-max_lines:] if len(lines) > max_lines else lines
        
        return jsonify({
            'success': True,
            'logs': [line.strip() for line in lines if line.strip()],
            'total_lines': len(lines)
        })
    except Exception as e:
        logger.error(f"Error reading logs: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/logs/clear', methods=['POST'])
def clear_logs():
    """Clear the log file."""
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'w') as f:
                f.write('')
        logger.info("[SYSTEM] Log file cleared")
        return jsonify({'success': True, 'message': 'Logs cleared'})
    except Exception as e:
        logger.error(f"Error clearing logs: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/logs/ui-activity', methods=['POST'])
def log_ui_activity():
    """Log UI activity from the frontend."""
    try:
        data = request.json
        activity = data.get('activity', 'UNKNOWN')
        details = data.get('details', {})
        timestamp = data.get('timestamp', datetime.now().isoformat())
        
        # Format details as JSON string
        details_str = json.dumps(details, default=str) if details else '{}'
        
        log_msg = f"[UI] {activity} | {details_str}"
        logger.info(log_msg)
        
        return jsonify({'success': True, 'message': 'UI activity logged'})
    except Exception as e:
        logger.error(f"Error logging UI activity: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/user-info')
def user_info():
    """Get current user information."""
    check_start_time = datetime.now()
    
    # Log authentication check initiation
    log_auth_event("AUTH_CHECK_START", "Authentication check initiated")
    
    if 'authenticated' not in session or not session['authenticated']:
        check_duration = (datetime.now() - check_start_time).total_seconds() * 1000
        log_auth_event("AUTH_CHECK_RESULT", "Not authenticated (no session)", 
                      check_duration_ms=check_duration)
        return jsonify({
            'authenticated': False,
            'error': 'Not authenticated'
        })
    
    # Verify authentication by testing the client
    is_valid = False
    try:
        workspace_url = session.get('workspace_url', DEFAULT_WORKSPACE_URL)
        user_email = session.get('user_email', 'Unknown')
        
        config = Config(host=workspace_url, auth_type='external-browser')
        client = WorkspaceClient(config=config)
        # Try to get current user to verify auth is still valid
        current_user = client.current_user.me()
        is_valid = True
        # Update session with current user info
        if hasattr(current_user, 'user_name'):
            session['user_email'] = current_user.user_name
            user_email = current_user.user_name
        
        check_duration = (datetime.now() - check_start_time).total_seconds() * 1000
        log_auth_event("AUTH_CHECK_RESULT", "Authentication valid", 
                      user=user_email, workspace_url=workspace_url,
                      check_duration_ms=check_duration)
    except Exception as e:
        # Authentication is invalid or expired
        check_duration = (datetime.now() - check_start_time).total_seconds() * 1000
        error_msg = str(e)
        logger.warning(f"Authentication check failed: {e}")
        log_auth_event("AUTH_CHECK_RESULT", "Authentication check failed", 
                      error=error_msg, check_duration_ms=check_duration,
                      traceback=traceback.format_exc())
        session['authenticated'] = False
        is_valid = False
    
    return jsonify({
        'authenticated': is_valid,
        'user_email': session.get('user_email', 'Unknown') if is_valid else None,
        'workspace_url': session.get('workspace_url', DEFAULT_WORKSPACE_URL) if is_valid else None
    })


@app.route('/auth/reauthenticate', methods=['POST'])
def reauthenticate():
    """Re-authenticate with SSO."""
    reauth_start_time = datetime.now()
    
    try:
        workspace_url = request.json.get('workspace_url', DEFAULT_WORKSPACE_URL).strip() if request.is_json else DEFAULT_WORKSPACE_URL
        if not workspace_url:
            workspace_url = DEFAULT_WORKSPACE_URL
        
        log_auth_event("REAUTH_INITIATE", f"Starting re-authentication", 
                      workspace_url=workspace_url, timestamp=reauth_start_time.isoformat())
        
        # Clear existing session
        session.clear()
        
        # Store workspace URL in session for callback
        session['workspace_url'] = workspace_url
        session['sso_in_progress'] = True
        
        # Initialize Databricks client with SSO
        config = Config(host=workspace_url, auth_type='external-browser')
        client = WorkspaceClient(config=config)
        
        # Test connection by getting current user
        client_init_time = datetime.now()
        current_user = client.current_user.me()
        client_check_duration = (datetime.now() - client_init_time).total_seconds() * 1000
        
        # Authentication successful
        session['authenticated'] = True
        session['workspace_url'] = workspace_url
        session['user_email'] = current_user.user_name if hasattr(current_user, 'user_name') else 'Unknown'
        session['sso_in_progress'] = False
        
        reauth_duration = (datetime.now() - reauth_start_time).total_seconds() * 1000
        log_auth_event("REAUTH_SUCCESS", f"Re-authentication successful", 
                      workspace_url=workspace_url, user=session['user_email'],
                      duration_ms=reauth_duration, client_check_duration_ms=client_check_duration)
        
        return jsonify({
            'success': True,
            'message': 'Re-authentication successful',
            'user': session['user_email'],
            'workspace_url': workspace_url
        })
    
    except Exception as e:
        session['sso_in_progress'] = False
        session['authenticated'] = False
        error_msg = str(e)
        reauth_duration = (datetime.now() - reauth_start_time).total_seconds() * 1000
        
        log_auth_event("REAUTH_ERROR", f"Re-authentication failed", 
                      workspace_url=workspace_url, error=error_msg, 
                      duration_ms=reauth_duration, traceback=traceback.format_exc())
        
        return jsonify({
            'success': False,
            'error': error_msg
        }), 400


if __name__ == '__main__':
    logger.info("=" * 80)
    logger.info("Starting Databricks API Explorer")
    logger.info(f"Default workspace: {DEFAULT_WORKSPACE_URL}")
    logger.info(f"Log file: {LOG_FILE}")
    logger.info("=" * 80)
    
    # Run the app
    app.run(debug=True, host='0.0.0.0', port=5000)

