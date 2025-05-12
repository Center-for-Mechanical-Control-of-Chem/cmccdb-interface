
import flask
import requests
import os
import json
import urllib
import base64
import uuid

bp = flask.Blueprint("authentication", __name__, url_prefix="/client", template_folder=".")

GITHUB_CREDENTIALS_FILE = "/app/credentials/github_auth_credentials.json"
def gh_client_params(localhost=False, dev=False):
    if dev: 
        if os.path.exists(GITHUB_CREDENTIALS_FILE):
            with open(GITHUB_CREDENTIALS_FILE) as credentials:
                creds = json.load(credentials)
            CLIENT_ID = creds.get("dev_client_id")
            CLIENT_SECRET = creds.get("dev_client_secret")
    elif localhost:
        if os.path.exists(GITHUB_CREDENTIALS_FILE):
            with open(GITHUB_CREDENTIALS_FILE) as credentials:
                creds = json.load(credentials)
            CLIENT_ID = creds.get("localhost_client_id")
            CLIENT_SECRET = creds.get("localhost_client_secret")
    else:
        CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")
        CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")
        if CLIENT_ID is None or len(CLIENT_ID.strip()) == 0:
            if os.path.exists(GITHUB_CREDENTIALS_FILE):
                with open(GITHUB_CREDENTIALS_FILE) as credentials:
                    creds = json.load(credentials)
                CLIENT_ID = creds.get("client_id")
                CLIENT_SECRET = creds.get("client_secret")
        
        if CLIENT_ID is None:
            if os.path.exists(GITHUB_CREDENTIALS_FILE):
                raise ValueError(f"no GitHub client info available (edit `{GITHUB_CREDENTIALS_FILE}`)")
            else:
                raise ValueError(f"no GitHub client info available (create `{GITHUB_CREDENTIALS_FILE}`)")

    return {
        "client_id":CLIENT_ID,
        "client_secret":CLIENT_SECRET
    }

SCOPE = "read:user,read:org"
DEVICE_AUTH_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
@bp.route("/api/device-authenticate", methods=["GET"])
def gh_device_authenticate():
    origin_url = flask.request.args.get('origin_url')
    creds = gh_client_params(
        localhost=origin_url is not None and '127.0.0.1' in origin_url,
        dev=origin_url is not None and 'mechanochemistry-db-01-dev' in origin_url
        )
    device_code = flask.request.args.get("device_code")
    if device_code is None:
        device_info = requests.post(
            DEVICE_AUTH_URL,
            headers={"Accept":"application/json"},
            json={
                "client_id":creds['client_id'],
                "scope":SCOPE
            }
        ).json()
        origin_url = flask.request.args.get("origin_url")
        if origin_url is not None:
            device_info["origin_url"] = origin_url
        query = urllib.parse.urlencode(device_info)
        return flask.redirect("/auth/device?"+query)
    else:
        auth_info = requests.post(
            TOKEN_URL,
            headers={"Accept":"application/json"},
            json={
                "client_id":creds['client_id'],
                "device_code":device_code,
                "grant_type":"urn:ietf:params:oauth:grant-type:device_code"
            }
        ).json()
        flask.session['github_auth_token'] = auth_info['access_token']
        origin_url = flask.request.args.get("origin_url")
        if origin_url is None:
            return flask.redirect("/")
        else:
            return flask.redirect(origin_url)

@bp.route("/api/logout", methods=["GET"])
def gh_logout():
    email = flask.session.get("github_email")
    if email is not None:
        del flask.session["github_email"]
        del flask.session["github_auth_token"]
        del flask.session["github_name"]
        del flask.session["github_username"]
        del flask.session["github_cmcc_status"]
        del flask.session["github_cmcc_owner"]
    origin_url = flask.request.args.get("origin_url")
    if origin_url is None:
        return flask.redirect("/")
    else:
        return flask.redirect(origin_url)

@bp.route("/api/user-info", methods=["GET"])
def gh_get_cache_user_info():
    email = flask.session.get("github_email")
    if email is None:
        auth_token = flask.session.get('github_auth_token')
        if auth_token is None:
            return None
        user_info, cmcc_status = gh_user_email_data(auth_token)
        flask.session["github_email"] = user_info["email"]
        flask.session["github_username"] = user_info["login"]
        flask.session["github_name"] = user_info["name"]
        flask.session["github_cmcc_status"] = cmcc_status['member'] == 204
        flask.session["github_cmcc_owner"] = cmcc_status['owner']
    return {
        "email":flask.session["github_email"],
        "username":flask.session["github_username"],
        "name":flask.session["github_name"],
        "member":flask.session["github_cmcc_status"],
        "owner":flask.session["github_cmcc_owner"],
    }
    # return flask.jsonify({"user":user_info, "email":user_email})

GITHUB_API_VERSION = "2022-11-28"
def get_oauth_headers(token=None, return_json=True):
    headers = {"X-GitHub-Api-Version": GITHUB_API_VERSION}
    if return_json:
        headers["Accept"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return headers

USER_CMCC_MEMBER = "https://api.github.com/orgs/Center-for-Mechanical-Control-of-Chem/members/{username}"
USER_CMCC_ADMIN = "https://api.github.com/orgs/Center-for-Mechanical-Control-of-Chem/members?role=admin"
USER_BASE_URL = "https://api.github.com/user"
def gh_user_email_data(token):
    headers = get_oauth_headers(token)
    user_info = requests.get(
        USER_BASE_URL,
        headers=headers
    ).json()
    org_info = requests.get(
        USER_CMCC_MEMBER.format(username=user_info['login']),
        headers=headers
    ).status_code
    org_admins = requests.get(
        USER_CMCC_ADMIN,
        headers=headers
    ).json()
    user = user_info['login']
    is_admin = any(
        u['login']==user
        for u in org_admins
    )
    return user_info, {"member":org_info, "owner":is_admin}

def resolve_redirect_uri():
    origin_url = flask.request.args.get('origin_url', None)
    redirect_uri = flask.request.args.get('redirect_uri')
    if redirect_uri is None:
        if origin_url is None:
            redirect_uri = 'https://mechanochemistry.chem.tamu.edu/api/github-callback'
        else:
            origin_parse = urllib.parse.urlsplit(origin_url)
            redirect_uri = urllib.parse.urlunsplit((
                origin_parse.scheme,
                origin_parse.netloc,
                '/api/github-callback',
                origin_parse.query,
                origin_parse.fragment
            ))
    return redirect_uri

GITHUB_OAUTH_URL = "https://github.com/login/oauth/authorize"
@bp.route("/api/authenticate", methods=["GET"])
def gh_authenticate():
    redirect_uri = resolve_redirect_uri()
    state = str(uuid.uuid4())
    flask.session["gh_salt"] = state
    flask.session["gh_redirect_uri"] = redirect_uri
    params = gh_client_params(
        localhost='127.0.0.1' in redirect_uri,
        dev='mechanochemistry-db-01-dev' in redirect_uri
        )
    query_params = {
            "redirect_uri":redirect_uri,
            "scope":SCOPE,
            "client_id":params["client_id"],
            "state":state
        }
    origin_url = flask.request.args.get("origin_url")
    if origin_url is not None:
        query_params["origin_url"] = origin_url
    return flask.redirect(
        GITHUB_OAUTH_URL + "?" + urllib.parse.urlencode(query_params)
    )

@bp.route("/api/github-callback", methods=["GET"])
def gh_oauth_callback():
    redirect_uri = flask.session.get("gh_redirect_uri")
    if redirect_uri is None:
        redirect_uri = resolve_redirect_uri()
    params = gh_client_params(    
        localhost='127.0.0.1' in redirect_uri,
        dev='mechanochemistry-db-01-dev' in redirect_uri
        )
    state = flask.session.get("gh_salt") # use this to avoid MiM attacks
    auth_info = requests.post(
        TOKEN_URL,
        headers={"Accept":"application/json"},
        json={
            "code":flask.request.args.get('code'),
            'client_id':params['client_id'],
            'client_secret':params['client_secret'],
            'redirect_uri':redirect_uri
        }
    ).json()
    flask.session['github_auth_token'] = auth_info['access_token']
    origin_url = auth_info.get("origin_url")
    if origin_url is None:
        return flask.redirect("/")
    else:
        return flask.redirect(origin_url)
