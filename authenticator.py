import getpass
import http.client          
import urllib.request, urllib.parse, urllib.error
import re
from optparse import OptionParser
import sys
import logging
import time
import atexit
import socket
import gc
import netrc
import keyring 
import os
import threading
import time

# Globals, set right in the beginning
username = None
password = None
args = None


class LoginState:
  AlreadyLoggedIn, InvalidCredentials, Successful = list(range(3))
  
class FirewallState:
  Start, LoggedIn, End = list(range(3))

# To logout when exit from program
def atexit_logout():
    """
    Log out from firewall authentication. This is supposed to run whenever the
    program exits.
    """
    
    # state = FirewallState.Start
    
    logger = logging.getLogger("FirewallLogger")
    
    if state == FirewallState.LoggedIn:
      url = args[0]
      logouturl = urllib.parse.ParseResult(url.scheme, url.netloc, "/logout",
                                       url.params, url.query, url.fragment)
      try:
        logger.info("Logging out with URL %s" % logouturl.geturl())
        conn = http.client.HTTPSConnection(logouturl.netloc)
        conn.request("GET", logouturl.path + "?" + logouturl.query)
        response = conn.getresponse()
        response.read()
      except (http.client.HTTPException, socket.error) as e:
        # Just print an error message
        logger.info("Exception |%s| while logging out." % e)
      finally:
        conn.close()
        keyring.delete_password("ISMFirewall", "keepAliveUrl")
    print("Exiting...")
    os._exit(1)
    
# to rest the user credentials
def reset_login():
    if(keyring.get_password("ISMFirewall","username")):
      print("Removing username and password...")
      keyring.delete_password("ISMFirewall", "username")
      keyring.delete_password("ISMFirewall", "password")
    atexit_logout()
    
    

# input thread
def input_thread():
    global user_input
    while True:
      user_input = input()
      if user_input.lower() == 'q':
        atexit_logout()
        break
      elif user_input.lower() == "rq":
        reset_login()
        break
          
          




def start_func():
  """
  This is called when we're in the initial state. If we're already logged in, we
  can't do anything much. If we're not, we should transition to the
  not-logged-in state.
  """
  ERROR_RETRY_SECS = 5
  LOGGED_IN_RETRY_SECS = 5
  logger = logging.getLogger("FirewallLogger")
  
  prevKeepAliveUrl = keyring.get_password("ISMFirewall", "keepAliveUrl")
  if prevKeepAliveUrl: # Prev session keepalive url.
    data = urllib.parse.urlparse(prevKeepAliveUrl)
    return (FirewallState.LoggedIn, 0 ,[data])

  try:
    loginstate, data = login()
    
  except (http.client.HTTPException, socket.error) as e:
    logger.info("Exception |%s| while trying to log in. Retrying in %d seconds." %
                (e, ERROR_RETRY_SECS))
    print("------------------------------------------------------------------------")
    print("Note: Sign-out of the ISM authentication page before running this script")
    print("------------------------------------------------------------------------")
    return (FirewallState.Start, ERROR_RETRY_SECS, None)

  # Check whether we're logged in
  if loginstate == LoginState.AlreadyLoggedIn:
    logger.info("You're already logged in (response code %d). Retrying in %d seconds." %
                (data, LOGGED_IN_RETRY_SECS))
    return (FirewallState.Start, LOGGED_IN_RETRY_SECS, None)
  elif loginstate == LoginState.InvalidCredentials:
    # Not much we can do.
    return (FirewallState.End, 0, [3])
  else:
    # Yay, we logged in.
    return (FirewallState.LoggedIn, 0, [data])

def logged_in_func(keepaliveurl):
  """
  Keep the firewall authentication alive by pinging a keepalive URL every few
  seconds. If there are any connection problems, keep trying with the same
  URL. If the keepalive URL doesn't work any more, go back to the start state.
  """
  logger = logging.getLogger("FirewallLogger")
  ERROR_RETRY_SECS = 5
  LOGGED_IN_SECS = 200
  try:
    keep_alive(keepaliveurl)
  except http.client.BadStatusLine:
    logger.info("The keepalive URL %s doesn't work. Attempting to log in again." %
                keepaliveurl.geturl())
    keyring.delete_password("ISMFirewall", "keepAliveUrl")
    return (FirewallState.Start, 0, None)
  except (http.client.HTTPException, socket.error) as e:
    logger.info("Exception |%s| while trying to keep alive. Retrying in %d seconds." %
                (e, ERROR_RETRY_SECS))
    return (FirewallState.LoggedIn, ERROR_RETRY_SECS, [keepaliveurl])

  # OK, the URL worked. That's good.
  return (FirewallState.LoggedIn, LOGGED_IN_SECS, [keepaliveurl])

state_functions = {
  FirewallState.Start: start_func,
  FirewallState.LoggedIn: logged_in_func,
  FirewallState.End: sys.exit
}

def run_state_machine():
  """
  Runs the state machine defined above.
  """
  global state
  state = FirewallState.Start
  global args
  sleeptime = 0
  atexit.register(atexit_logout)
  
  
  

  while True:
    statefunc = state_functions[state]
    if args is None:
      state, sleeptime, args = statefunc()
    else:
      state, sleeptime, args = statefunc(*args)
    if sleeptime > 0:
      time.sleep(sleeptime)



def login():
  """
  Attempt to log in. Returns AlreadyLoggedIn if we're already logged in,
  InvalidCredentials if the username and password given are incorrect, and
  Successful if we have managed to log in. Throws an exception if an error
  occurs somewhere along the process.
  """
  logger = logging.getLogger("FirewallLogger")
  # Find out where to auth
  
  try:
    
    print("Logging to the firewall...")
    conn = http.client.HTTPConnection("74.125.236.51:80")
    conn.request("GET", "/")
    response = conn.getresponse()
    # 200 leads to the auth page, so it means we're not logged in
    if (response.status != 200):
      return (LoginState.AlreadyLoggedIn, response.status)
    
    match = re.search(r'window.location="([^"]+)"', str(response.read())) 
    authlocation = match.group(1)
    
    # authlocation = response.getheader("Location")
  finally:
    conn.close()

  logger.info("The auth location is: %s" % authlocation)

  # Make a connection to the auth location
  parsedauthloc = urllib.parse.urlparse(authlocation)
  try:
    authconn = http.client.HTTPSConnection(parsedauthloc.netloc)
    authconn.request("GET", parsedauthloc.path + "?" + parsedauthloc.query)
    authResponse = authconn.getresponse()
    data = authResponse.read()
  finally:
    authconn.close()

  # Look for the right magic value in the data
  match = re.search(r"value=\"([0-9a-f]+)\"", str(data))
  magicString = match.group(1)
  logger.debug("The magic string is: " + magicString)

  # Now construct a POST request
  params = urllib.parse.urlencode({'username': username, 'password': password,
                             'magic': magicString, '4Tredir': '/'})
  headers = {"Content-Type": "application/x-www-form-urlencoded",
             "Accept": "text/plain"}

  try:
    postconn = http.client.HTTPSConnection(parsedauthloc.netloc)
    postconn.request("POST", "/", params, headers)

    # Get the response
    postResponse = postconn.getresponse()
    postData = postResponse.read()
  finally:
    postconn.close()
  
  keepaliveMatch = re.search(r'window.location="([^"]+)"', str(postData)) 
  
  if keepaliveMatch is None:
    # Whoops, unsuccessful -- probably the username and password didn't match
    
    logger.fatal("Authentication unsuccessful, check your username and password.")
    return (LoginState.InvalidCredentials, None)

  # The credentials are encrypted and stored in the Credential Manager, providing a secure storage location.
  keyring.set_password("ISMFirewall", "username", username) 
  keyring.set_password("ISMFirewall", "password", password)
  
  keepaliveURL = keepaliveMatch.group(1)
  
  keyring.set_password("ISMFirewall", "keepAliveUrl", keepaliveURL) 
  logger.info("The keep alive URL is: " + keepaliveURL)
  logger.debug(postData)
  return (LoginState.Successful, urllib.parse.urlparse(keepaliveURL))

def keep_alive(url):
  """
  Attempt to keep the connection alive by pinging a URL.
  """
  logger = logging.getLogger("FirewallLogger")
  logger.info("Sending request to keep alive.")
  # Connect to the firewall
  try:
    conn = http.client.HTTPSConnection(url.netloc)
    conn.request("GET", url.path + "?" + url.query)
    # This line raises an exception if the URL stops working. We catch it in
    # logged_in_func.
    response = conn.getresponse()

    logger.debug(str(response.status))
    logger.debug(response.read())
  finally:
    conn.close()
    gc.collect()

def get_credentials(options, args):
  """
  Get the username and password, from netrc, command line args or interactively.
  """
  username = None
  password = None

  if options.netrc:
    logger = logging.getLogger("FirewallLogger")
    try:
      info = netrc.netrc()
      cred = info.authenticators("172.31.1.251")
      if cred:
        return (cred[0], cred[2])
      logger.info("Could not find credentials in netrc file.")
    except:
      logger.info("Could not read from netrc file.")
  print("ISM Firewall Login\n")
  print("-----------------KEYBOARD GUIDE--------------------")
  print("Press 'q': Log out and Exit script")
  print("Press 'rq': Reset username, Log out and Exit script")
  print("---------------------------------------------------")
  username = keyring.get_password("ISMFirewall", "username")
  password = keyring.get_password("ISMFirewall", "password")
  
  if username and password:
    print("Logging In with username",username)
    return (username, password)
  else:
    if len(args) == 0:
      # Get the username from the input
      username = input("Username: ")
    else:
      # First member of args
      username = args[0]

    if len(args) <= 1:
      # Read the password without echoing it
      print("(You wont see password output on screen, just type the password and press enter):")
      password = getpass.getpass()
      
    else:
      password = args[1]
    
    return (username, password)

def init_logger(options):
  logger = logging.getLogger("FirewallLogger")
  logger.setLevel(logging.DEBUG)
  handler = logging.StreamHandler()
  if options.verbose:
    handler.setLevel(logging.DEBUG)
  else:
    handler.setLevel(logging.INFO)

  formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
  handler.setFormatter(formatter)
  logger.addHandler(handler)

"""
Main function
"""
def main(argv = None):
  
  
  if argv is None:
    argv = sys.argv[1:]

  # First generate help syntax
  usage = "Usage: %prog [options] [username [password]]"
  parser = OptionParser(usage = usage)
  parser.add_option("-v", "--verbose", action = "store_true", dest = "verbose",
                    help = "Print lots of debugging information")
  parser.add_option("-n", "--netrc", action = "store_true", dest = "netrc",
                    help = "Read credentials from netrc file")

  # Parse arguments
  (options, args) = parser.parse_args(argv)

  if len(args) > 2:
    parser.error("too many arguments")
    return 1

  init_logger(options)

  # Try authenticating!
  global username, password
  username, password = get_credentials(options, args)
  
  input_thread_1 = threading.Thread(target=input_thread, daemon=True)
  input_thread_1.start()
  run_state_machine()
  return 0

if __name__ == "__main__":
  user_input = None
  sys.exit(main())
