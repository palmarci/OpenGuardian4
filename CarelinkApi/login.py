import base64
import hashlib
import json
import logging
import os
import random
import re
import string
import uuid
from http.client import HTTPConnection
from random import randbytes
from time import sleep

import curlify
import OpenSSL
import requests
from seleniumwire import webdriver
import jwt
from datetime import datetime, timedelta
import pytz
import tzlocal

def setup_logging():
	HTTPConnection.debuglevel = 1
	logging.basicConfig()
	logging.getLogger().setLevel(logging.DEBUG)
	requests_log = logging.getLogger("requests.packages.urllib3")
	requests_log.setLevel(logging.DEBUG)
	requests_log.propagate = True

def random_b64_str(length):
	random_chars = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(length + 10))
	base64_string = base64.b64encode(random_chars.encode('utf-8')).decode('utf-8')
	return base64_string[:length]

def random_uuid():
	return str(uuid.UUID(bytes=randbytes(16)))

def random_android_model():
	models = ['SM-G973F', "SM-G988U1", "SM-G981W", "SM-G9600"]
	random.shuffle(models)
	return models[0]

def random_device_id():
	return hashlib.sha256(os.urandom(40)).hexdigest()

def create_csr(keypair, cn, ou, dc, o):
	"""
		reversed from the apk

		public byte[] getSignedPKCS10CSR(String common_name_unknown, String deviceId, String buildModel, String MssoOrg, PrivateKey privateKey, PublicKey publicKey) throws CertificateException {
			try {
				PKCS10CertRequest pKCS10CertRequest = new PKCS10CertRequest(publicKey);
				Signature signature = Signature.getInstance("SHA256withRSA");
				signature.initSign(privateKey);
				String common_name_unknown_r = common_name_unknown.replace("\"", "\\\"");
				String deviceid_r = deviceId.replace("\"", "\\\"");
				String buildmodel_r = buildModel.replace("\"", "\\\"");
				String mssoorg_r = MssoOrg.replace("\"", "\\\"");
				String buildmodel_final = buildmodel_r.replaceAll("[^a-zA-Z0-9]", "");
				if (buildmodel_final.isEmpty()) {
					buildmodel_final = "Undefined";
				}
				pKCS10CertRequest.sign(new X500Signer(signature, new X500Name("cn=\"" + common_name_unknown_r + "\", ou=\"" + deviceid_r + "\", dc=\"" + buildmodel_final + "\", o=\"" + mssoorg_r + "\"")));
				return pKCS10CertRequest.getSigned();
			} catch (Exception e) {
				if (C5913f.f16333a) {
					StringBuilder sb2 = new StringBuilder();
					sb2.append("Unable to generate certificate signing request: ");
					sb2.append(e);
				}
				throw new CertificateException("Unable to generate certificate signing request: " + e);
			}
		}
	"""
	req = OpenSSL.crypto.X509Req()

	#order is not checked
	req.get_subject().CN = cn
	req.get_subject().OU = ou
	req.get_subject().DC = dc
	req.get_subject().O = o

	req.set_pubkey(keypair)
	req.sign(keypair, 'sha256')

	csr = OpenSSL.crypto.dump_certificate_request(OpenSSL.crypto.FILETYPE_PEM, req)
	return csr

def reformat_csr(csr):
	# remove footer & header, re-encode with url safe base64
	csr = csr.decode()
	csr = csr.replace("\n", "")
	csr = csr.replace("-----BEGIN CERTIFICATE REQUEST-----", "")
	csr = csr.replace("-----END CERTIFICATE REQUEST-----", "")

	csr_raw = base64.b64decode(csr.encode())
	csr = base64.urlsafe_b64encode(csr_raw).decode()
	return csr

def do_captcha(url, redirect_url):
	driver = webdriver.Firefox()
	driver.get(url)

	while True:
		for request in driver.requests:  
			if request.response:  
				if request.response.status_code == 302:
					if "location" in request.response.headers:
						location = request.response.headers["location"]
						if redirect_url in location:
							code = re.search(r"code=(.*)&", location).group(1)
							state = re.search(r"state=(.*)", location).group(1)
							driver.quit()
							return (code, state)
		sleep(0.1)

def resolve_endpoint_config(discovery_url, is_us_region=False):
	discover_resp = json.loads(requests.get(discovery_url).text)
	sso_url = None

	for c in discover_resp["CP"]:
		if c['region'].lower() == "us" and is_us_region:
			sso_url = c['SSOConfiguration']
		elif c['region'].lower() == "eu" and not is_us_region:
			sso_url = c['SSOConfiguration']
		
	if sso_url is None:
		raise Exception("Could not get SSO config url")
	
	sso_config = json.loads(requests.get(sso_url).text)
	api_base_url = f"https://{sso_config['server']['hostname']}:{sso_config['server']['port']}/{sso_config['server']['prefix']}"
	return sso_config, api_base_url

def write_datafile(obj, filename):
	print("wrote data file")
	with open(filename, 'w') as f:
		json.dump(obj, f, indent=4)

def do_login(endpoint_config):
	sso_config, api_base_url = endpoint_config
	# step 1 initialize
	client_init_uuid = random_uuid() # this is not used elsewhere?
	data = {
		'client_id': sso_config['oauth']['client']['client_ids'][0]['client_id'],
		"nonce" :  random_uuid()
	}
	headers = {
		'device-id': base64.b64encode(random_device_id().encode()).decode() # this is not used elsewhere?
	}
	client_init_url = api_base_url + sso_config["mag"]["system_endpoints"]["client_credential_init_endpoint_path"]
	client_init_req = requests.post(client_init_url, data=data, headers=headers)
	client_init_response = json.loads(client_init_req.text)

	# step 2 authorize
	client_code_verifier = base64.urlsafe_b64encode(os.urandom(40)).decode('utf-8')
	client_code_verifier = re.sub('[^a-zA-Z0-9]+', '', client_code_verifier)
	client_code_challange = hashlib.sha256(client_code_verifier.encode('utf-8')).digest()
	client_code_challange = base64.urlsafe_b64encode(client_code_challange).decode('utf-8')
	client_code_challange = client_code_challange.replace('=', '')

	client_state = random_b64_str(22) # whats this ?
	auth_params = {
		'client_id': client_init_response["client_id"],
		'response_type' : 'code',
		'display' : 'social_login',
		'scope': sso_config["oauth"]["client"]["client_ids"][0]['scope'],
		'redirect_uri': sso_config["oauth"]["client"]["client_ids"][0]['redirect_uri'],
		'code_challenge' : client_code_challange,
		'code_challenge_method': 'S256',
	 	'state': client_state
	}
	authorize_url = api_base_url + sso_config["oauth"]["system_endpoints"]["authorization_endpoint_path"]
	providers = json.loads(requests.get(authorize_url, params=auth_params).text) # this will redirect
	captcha_url = providers["providers"][0]["provider"]["auth_url"]

	# step 3 captcha login and consent
	print(f"captcha url: {captcha_url}")
	captcha_code, captcha_sso_state = do_captcha(captcha_url, sso_config["oauth"]["client"]["client_ids"][0]['redirect_uri'])
	print(f"sso state after captcha: {captcha_sso_state}")

	# step 4 registraton
	register_device_id = random_device_id()
	client_auth_str = f"{client_init_response['client_id']}:{client_init_response['client_secret']}"

	android_model = random_android_model()
	android_model_safe = re.sub(r"[^a-zA-Z0-9]", "", android_model)
	keypair = OpenSSL.crypto.PKey()

	# ignoring sso_config['mag']['mobile_sdk']['client_cert_rsa_keybits'], due to the app clamps the minimum size:
	#    if (i < 2048) 
	#       i = 2048;
	keypair.generate_key(OpenSSL.crypto.TYPE_RSA, rsa_keysize)
	csr = create_csr(keypair, "socialLogin", register_device_id, android_model_safe, sso_config["oauth"]["client"]["organization"])

	reg_headers = {
		'device-name': base64.b64encode(android_model.encode()).decode(),
		'authorization' : f"Bearer {captcha_code}",
		'cert-format': 'pem',
		'client-authorization': "Basic " + base64.b64encode(client_auth_str.encode()).decode(),
		'create-session': 'true',
		'code-verifier': client_code_verifier,
		'device-id': base64.b64encode(register_device_id.encode()).decode(),
		"redirect-uri": sso_config["oauth"]["client"]["client_ids"][0]['redirect_uri']
	}
	csr = reformat_csr(csr)
	reg_url = api_base_url + sso_config["mag"]["system_endpoints"]["device_register_endpoint_path"]
	reg_req = requests.post(reg_url, headers=reg_headers, data=csr)
	if reg_req.status_code != 200:
		print(f"\n\n{curlify.to_curl(reg_req.request)}")
		raise Exception(f'Could not register: {json.loads(reg_req.text)["error_description"]}')

	# TODO: step 5 token
	token_req_url = api_base_url + sso_config["oauth"]["system_endpoints"]["token_endpoint_path"]
	token_req_data = {
		"assertion" : reg_req.headers["id-token"],
		"client_id" : client_init_response['client_id'],
		"client_secret" : client_init_response['client_secret'],
		'scope': sso_config["oauth"]["client"]["client_ids"][0]['scope'],
		"grant_type" : reg_req.headers["id-token-type"] 
	}
	token_req = requests.post(token_req_url, headers={"mag-identifier" : reg_req.headers["mag-identifier"]}, data=token_req_data)
	if token_req.status_code != 200:
		print(f"\n\n{curlify.to_curl(token_req.request)}")
		raise Exception("Could not get token data")
	
	token_data = json.loads(token_req.text)
	print(f"got token data from server")

	token_data["client_id"] = token_req_data["client_id"]
	token_data["client_secret"] = token_req_data["client_secret"]
	del token_data["expires_in"]
	del token_data["token_type"]
	token_data["mag-identifier"] = reg_req.headers["mag-identifier"]

	write_datafile(token_data, logindata_file)
	return token_data

def do_refresh(token_data, endpoint_config):
	sso_config, api_base_url = endpoint_config
	token_req_url = api_base_url + sso_config["oauth"]["system_endpoints"]["token_endpoint_path"]

	data = {
		'refresh_token': token_data['refresh_token'],
		'client_id':     token_data['client_id'],
		'client_secret': token_data['client_secret'],
		'grant_type':    'refresh_token'
	}
	headers = {
		'mag-identifier': token_data['mag-identifier']
	}
	r = requests.post(url=token_req_url, data=data, headers=headers)
	print(f"got {r.status_code} for refresh token")
	new_data = json.loads(r.text)
	token_data["access_token"] = new_data["access_token"]
	token_data["refresh_token"] = new_data["refresh_token"]
	write_datafile(token_data, logindata_file)
	return token_data

def is_token_valid(utc_timestamp):
	utc_dt = datetime.utcfromtimestamp(utc_timestamp)
	aware_utc_dt = utc_dt.replace(tzinfo=pytz.utc)
	local = tzlocal.get_localzone().key
	print(f"got current timezone: {local}")
	tz = pytz.timezone(local)
	valid_final = aware_utc_dt.astimezone(tz)
	valid_final = valid_final.replace(tzinfo=None)
	print(f"token validity: until {valid_final} local time")
	now = datetime.now()
	if valid_final > (now + timedelta(minutes=1)):
		return True
	else:
		return False

def read_data_file(file):
	token_data = None
	if os.path.isfile(file):
		try:
			token_data = json.loads(open(file, "r").read())
		except json.JSONDecodeError:
			print("failed parsing json")
	
		if token_data is not None:
			required_fields = ["access_token", "refresh_token", "scope", "client_id", "client_secret", "mag-identifier"]
			for i in required_fields:
				if i not in token_data:
					print(f"field {i} is missing from data file")
					return None
	return token_data

# config
is_debug = False
logindata_file = 'logindata.json'
discovery_url = 'https://clcloud.minimed.eu/connect/carepartner/v6/discover/android/3.1'
rsa_keysize = 2048

def main():
	if is_debug:
		setup_logging()

	token_data = read_data_file(logindata_file)
	endpoint_config = resolve_endpoint_config(discovery_url)
	
	if token_data == None:
		print(f"could not read login data from file, starting login...")
		token_data = do_login(endpoint_config)
	else:
		print(f"read token data from file")
		
	token = token_data["access_token"]
	header = jwt.get_unverified_header(token)
	decoded_data = jwt.decode(token, algorithms=[header["alg"]], options={"verify_signature": False})
	print(f"decoded access token, valid for {decoded_data['token_details']['name']}")

	if not is_token_valid(decoded_data["exp"]):
		print(f"warning! token is invalid, refreshing...")
		token_data = do_refresh(token_data, endpoint_config)
	else:
		print(f"token is valid!")

	# this is only a quick proof of concept, i will be researching the connect app's endpoints
	print(f"querying web browser api")
	r = requests.get(url='https://carelink.minimed.eu/patient/connect/data', headers={'Authorization': f'Bearer {token_data["access_token"]}'})
	if r.status_code == 200:
		print("data query successful, saving to file")
		d = json.loads(r.text)
		write_datafile(d, "data.json")
	else:
		print(f"error: got {r.status_code} {r.text}")

main()