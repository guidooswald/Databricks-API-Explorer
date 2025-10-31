// Global app JavaScript

let authCheckInterval = null;

// Log UI activity function (may be overridden by index.html)
async function logUIActivity(activity, details = {}) {
    try {
        await fetch('/api/logs/ui-activity', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                activity: activity,
                details: details,
                timestamp: new Date().toISOString()
            })
        });
    } catch (error) {
        console.error('Failed to log UI activity:', error);
    }
}

// Check authentication status
async function checkAuthStatus(showLoading = false, isManual = false) {
    const checkAuthBtn = document.getElementById('checkAuthBtn');
    const checkAuthBtnIcon = document.getElementById('checkAuthBtnIcon');
    const originalIcon = checkAuthBtnIcon ? checkAuthBtnIcon.textContent : '🔍';
    
    // Log authentication check start
    if (isManual) {
        await logUIActivity('AUTH_CHECK_MANUAL', {
            trigger: 'user_button_click',
            timestamp: new Date().toISOString()
        });
    } else {
        await logUIActivity('AUTH_CHECK_AUTO', {
            trigger: 'automatic_check',
            timestamp: new Date().toISOString()
        });
    }
    
    const checkStartTime = Date.now();
    
    if (showLoading && checkAuthBtn) {
        checkAuthBtn.disabled = true;
        if (checkAuthBtnIcon) {
            checkAuthBtnIcon.textContent = '⏳';
        }
    }
    
    try {
        const response = await fetch('/api/user-info');
        const checkDuration = Date.now() - checkStartTime;
        const data = await response.json();
        
        const authStatus = document.getElementById('authStatus');
        const reAuthBtn = document.getElementById('reAuthBtn');
        const logoutBtn = document.getElementById('logoutBtn');
        
        if (data.authenticated) {
            authStatus.innerHTML = `
                <span class="badge bg-success">Authenticated</span>
                <span class="ms-2">${data.user_email || 'Unknown'}</span>
            `;
            reAuthBtn.style.display = 'inline-block';
            logoutBtn.style.display = 'inline-block';
            
            // Log successful authentication check
            await logUIActivity('AUTH_CHECK_SUCCESS', {
                authenticated: true,
                user_email: data.user_email || 'Unknown',
                workspace_url: data.workspace_url || 'Unknown',
                duration_ms: checkDuration,
                is_manual: isManual
            });
            
            // Enable API call button if on main page
            if (window.location.pathname === '/' || window.location.pathname === '/index') {
                const callApiBtn = document.getElementById('callApiBtn') || 
                                 document.querySelector('button[onclick="callApi()"]');
                if (callApiBtn) {
                    callApiBtn.disabled = false;
                    callApiBtn.title = '';
                }
            }
            
            // Show success feedback
            if (showLoading && checkAuthBtnIcon) {
                checkAuthBtnIcon.textContent = '✅';
                setTimeout(() => {
                    if (checkAuthBtnIcon) {
                        checkAuthBtnIcon.textContent = originalIcon;
                    }
                }, 2000);
            }
        } else {
            authStatus.innerHTML = `
                <span class="badge bg-danger">Not Authenticated</span>
            `;
            reAuthBtn.style.display = 'inline-block';
            logoutBtn.style.display = 'none';
            
            // Log failed authentication check
            await logUIActivity('AUTH_CHECK_FAILED', {
                authenticated: false,
                duration_ms: checkDuration,
                is_manual: isManual,
                error: data.error || 'Not authenticated'
            });
            
            // If on main page and not authenticated, disable API calls
            if (window.location.pathname === '/' || window.location.pathname === '/index') {
                const callApiBtn = document.getElementById('callApiBtn') || 
                                 document.querySelector('button[onclick="callApi()"]');
                if (callApiBtn) {
                    callApiBtn.disabled = true;
                    callApiBtn.title = 'Please authenticate first';
                }
            }
            
            // Show error feedback
            if (showLoading && checkAuthBtnIcon) {
                checkAuthBtnIcon.textContent = '❌';
                setTimeout(() => {
                    if (checkAuthBtnIcon) {
                        checkAuthBtnIcon.textContent = originalIcon;
                    }
                }, 2000);
            }
        }
    } catch (error) {
        const checkDuration = Date.now() - checkStartTime;
        console.error('Error checking auth status:', error);
        
        // Log error during authentication check
        await logUIActivity('AUTH_CHECK_ERROR', {
            error: error.message,
            duration_ms: checkDuration,
            is_manual: isManual,
            stack: error.stack
        });
        
        const authStatus = document.getElementById('authStatus');
        if (authStatus) {
            authStatus.innerHTML = `
                <span class="badge bg-warning">Error checking status</span>
            `;
        }
        
        // Show error feedback
        if (showLoading && checkAuthBtnIcon) {
            checkAuthBtnIcon.textContent = '⚠️';
            setTimeout(() => {
                if (checkAuthBtnIcon) {
                    checkAuthBtnIcon.textContent = originalIcon;
                }
            }, 2000);
        }
    } finally {
        if (showLoading && checkAuthBtn) {
            checkAuthBtn.disabled = false;
        }
    }
}

// Manual check authentication status (called by button)
async function checkAuthStatusManual() {
    await checkAuthStatus(true, true);
}

// Re-authenticate
async function reAuthenticate() {
    const workspaceUrl = prompt('Enter Databricks workspace URL:', 'https://adb-984752964297111.11.azuredatabricks.net');
    
    if (!workspaceUrl) {
        await logUIActivity('REAUTH_CANCELLED', {
            reason: 'user_cancelled_prompt',
            timestamp: new Date().toISOString()
        });
        return;
    }
    
    await logUIActivity('REAUTH_INITIATED', {
        workspace_url: workspaceUrl,
        timestamp: new Date().toISOString()
    });
    
    const reAuthStartTime = Date.now();
    const reAuthBtn = document.getElementById('reAuthBtn');
    const originalText = reAuthBtn.innerHTML;
    reAuthBtn.disabled = true;
    reAuthBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Authenticating...';
    
    try {
        const response = await fetch('/auth/reauthenticate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ workspace_url: workspaceUrl })
        });
        
        const reAuthDuration = Date.now() - reAuthStartTime;
        const data = await response.json();
        
        if (data.success) {
            await logUIActivity('REAUTH_SUCCESS', {
                workspace_url: workspaceUrl,
                user_email: data.user || 'Unknown',
                duration_ms: reAuthDuration,
                timestamp: new Date().toISOString()
            });
            
            // Refresh auth status
            await checkAuthStatus(false, false);
            
            // If on main page, enable API calls
            if (window.location.pathname === '/' || window.location.pathname === '/index') {
                const callApiBtn = document.getElementById('callApiBtn') || 
                                 document.querySelector('button[onclick="callApi()"]');
                if (callApiBtn) {
                    callApiBtn.disabled = false;
                    callApiBtn.title = '';
                }
            }
            
            // Show success message
            alert('Re-authentication successful!');
        } else {
            await logUIActivity('REAUTH_FAILED', {
                workspace_url: workspaceUrl,
                error: data.error || 'Unknown error',
                duration_ms: reAuthDuration,
                timestamp: new Date().toISOString()
            });
            alert('Re-authentication failed: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        const reAuthDuration = Date.now() - reAuthStartTime;
        await logUIActivity('REAUTH_ERROR', {
            workspace_url: workspaceUrl,
            error: error.message,
            duration_ms: reAuthDuration,
            stack: error.stack,
            timestamp: new Date().toISOString()
        });
        alert('Error during re-authentication: ' + error.message);
    } finally {
        reAuthBtn.disabled = false;
        reAuthBtn.innerHTML = originalText;
    }
}

async function logout() {
    if (!confirm('Are you sure you want to logout?')) {
        await logUIActivity('LOGOUT_CANCELLED', {
            reason: 'user_cancelled_confirmation',
            timestamp: new Date().toISOString()
        });
        return;
    }
    
    await logUIActivity('LOGOUT_INITIATED', {
        timestamp: new Date().toISOString()
    });
    
    const logoutStartTime = Date.now();
    
    try {
        const response = await fetch('/auth/logout', {
            method: 'POST'
        });
        const logoutDuration = Date.now() - logoutStartTime;
        const data = await response.json();
        
        if (data.success) {
            await logUIActivity('LOGOUT_SUCCESS', {
                duration_ms: logoutDuration,
                timestamp: new Date().toISOString()
            });
            
            // Clear auth status check interval
            if (authCheckInterval) {
                clearInterval(authCheckInterval);
            }
            
            // Update UI
            await checkAuthStatus(false, false);
            
            // Redirect to login if not already there
            if (window.location.pathname !== '/login') {
                window.location.href = '/login';
            }
        } else {
            await logUIActivity('LOGOUT_FAILED', {
                error: data.error || 'Unknown error',
                duration_ms: logoutDuration,
                timestamp: new Date().toISOString()
            });
            alert('Error logging out: ' + data.error);
        }
    } catch (error) {
        const logoutDuration = Date.now() - logoutStartTime;
        await logUIActivity('LOGOUT_ERROR', {
            error: error.message,
            duration_ms: logoutDuration,
            stack: error.stack,
            timestamp: new Date().toISOString()
        });
        alert('Error logging out: ' + error.message);
    }
}

// Utility function to format JSON
function formatJSON(obj) {
    return JSON.stringify(obj, null, 2);
}

// Initialize auth status check on page load
document.addEventListener('DOMContentLoaded', function() {
    logUIActivity('PAGE_LOADED', {
        path: window.location.pathname,
        timestamp: new Date().toISOString()
    });
    
    checkAuthStatus(false, false);
    // Auto auth check every 5 minutes (300000ms)
    authCheckInterval = setInterval(() => {
        checkAuthStatus(false, false);
    }, 300000);
});

// Cleanup on page unload
window.addEventListener('beforeunload', function() {
    if (authCheckInterval) {
        clearInterval(authCheckInterval);
    }
});

