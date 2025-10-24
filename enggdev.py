# main.py
import os
import sys
import time
import requests
import logging
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
from datetime import datetime

# --- Constants ---
LOGIN_URL = "https://cloud.enggenv.com/android_login.php"
HOME_URL = "https://cloud.enggenv.com/home.php"
# This is the AJAX endpoint that returns JSON data!
AAQ_DATA_URL = "https://cloud.enggenv.com/aaq/aaq_all_para.php"

MQTT_HOST = "cloud.pbrresearch.com"
MQTT_PORT = 1883
MQTT_TOPIC = "display/data/317050011"

# Device IDs
DEVICE_MILL_1 = "ENE03225"
DEVICE_MILL_2 = "ENE02822"

# Loop interval in seconds
LOOP_INTERVAL = 60


def setup_debug_logging():
    """Configures logging to print all debug info."""
    print("--- ENABLING DEBUG LOGGING ---")
    logging.basicConfig(level=logging.DEBUG, 
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    mqtt_logger = logging.getLogger("paho.mqtt.client")
    mqtt_logger.setLevel(logging.DEBUG)
    http_logger = logging.getLogger("urllib3")
    http_logger.setLevel(logging.DEBUG)
    http_logger.propagate = True
    requests_logger = logging.getLogger("requests")
    requests_logger.setLevel(logging.DEBUG)
    requests_logger.propagate = True
    print("--- DEBUG LOGGING ENABLED ---")


def load_config():
    """Loads configuration from .env file."""
    load_dotenv()
    config = {
        "web_user": os.getenv("WEB_USERNAME"),
        "web_pass": os.getenv("WEB_PASSWORD"),
        "mqtt_user": os.getenv("MQTT_USER"),
        "mqtt_pass": os.getenv("MQTT_PASS"),
    }
    if not all(config.values()):
        print("Error: Missing one or more .env variables.")
        sys.exit(1)
    return config


def login_to_site(config):
    """Logs into the website and returns an authenticated session."""
    print(f"Attempting to log in as {config['web_user']}...")
    session = requests.Session()

    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
    })

    login_payload = {
        "username": config["web_user"],
        "password": config["web_pass"]
    }
    
    try:
        response = session.post(LOGIN_URL, data=login_payload)
        response.raise_for_status() 
        print(f"Login POST complete. Landed on URL: {response.url}")
        
        if "home.php" not in response.url:
            print("Login Failed. Check credentials or site status.")
            return None
            
        print("Login Successful.")
        return session
        
    except requests.exceptions.RequestException as e:
        print(f"Login request failed: {e}")
        return None


def scrape_device_data(session, device_id, device_name):
    """
    Fetches device data from the AJAX endpoint that returns JSON.
    This is the endpoint called by the JavaScript aaq() function.
    """
    print(f"\nRequesting data for: {device_name} (ID: {device_id})")
    
    # This is how the JavaScript makes the request
    payload = {'id': device_id}
    
    # AJAX headers as used by the page
    ajax_headers = {
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Referer': HOME_URL,
        'Origin': 'https://cloud.enggenv.com'
    }
    
    try:
        print(f"Calling AJAX endpoint: {AAQ_DATA_URL}")
        response = session.post(AAQ_DATA_URL, data=payload, headers=ajax_headers)
        response.raise_for_status()
        
        print(f"Response status: {response.status_code}")
        print(f"Response content-type: {response.headers.get('content-type')}")
        print(f"Response length: {len(response.text)} chars")
        
        # Save for debugging
        debug_file = f"debug_{device_name}_ajax.json"
        with open(debug_file, "w", encoding="utf-8") as f:
            f.write(response.text)
        print(f"Saved response to: {debug_file}")
        
        # Try to parse as JSON
        try:
            data = response.json()
            print(f"✓ Received JSON data with keys: {list(data.keys())}")
            
            # The JSON should have arrays: para, last, unit, key
            # We need to find the SPM value
            # Based on the HTML structure, it should be in the parameters
            
            if 'para' in data and 'last' in data and 'unit' in data:
                # Print all parameters to see what's available
                print(f"\nAvailable parameters for {device_name}:")
                for i, (param, value, unit) in enumerate(zip(data['para'], data['last'], data['unit'])):
                    print(f"  {i}: {param} = {value} {unit}")
                
                # Look for SPM or similar parameter
                # Common names: SPM, PM2.5, PM10, Particulate Matter, etc.
                for i, param in enumerate(data['para']):
                    param_lower = param.lower()
                    if 'spm' in param_lower or 'pm' in param_lower or 'particulate' in param_lower:
                        value = data['last'][i]
                        print(f"\n✓ Found {param} = {value} for {device_name}")
                        return value
                
                # If no SPM found, maybe it's at a specific index?
                # Let's try the first non-temperature/humidity value
                for i, param in enumerate(data['para']):
                    if i >= 2:  # Skip temp and humidity (indices 0 and 1)
                        value = data['last'][i]
                        print(f"\n? Using {param} = {value} for {device_name} (first non-temp/humidity value)")
                        return value
                        
            else:
                print(f"✗ Unexpected JSON structure: {list(data.keys())}")
                
        except ValueError as e:
            print(f"✗ Response is not valid JSON: {e}")
            print(f"First 500 chars: {response.text[:500]}")
        
        return None
        
    except requests.exceptions.RequestException as e:
        print(f"✗ Request failed for {device_name}: {e}")
        return None


def publish_to_mqtt(config, mill_1_value, mill_2_value):
    """Connects to MQTT and publishes the data in the specified format."""
    
    message = f"SPM_2:{mill_2_value},SPM_1:{mill_1_value}"
    
    print("\n" + "="*50)
    print("MQTT PUBLISHING")
    print("="*50)
    print(f"Topic: {MQTT_TOPIC}")
    print(f"Message: {message}")
    print("="*50)
    
    try:
        client = mqtt.Client(protocol=mqtt.MQTTv311)
        client.on_log = lambda client, userdata, level, buf: print(f"MQTT LOG: {buf}")
        client.username_pw_set(config["mqtt_user"], config["mqtt_pass"])
        
        print("Connecting to MQTT broker...")
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.loop_start() 
        
        result = client.publish(MQTT_TOPIC, message)
        result.wait_for_publish(timeout=5)
        
        if result.is_published():
            print("✓ Successfully published to MQTT.")
        else:
            print("✗ Failed to publish message (timeout or other error).")

        client.loop_stop()
        client.disconnect()
        
    except Exception as e:
        print(f"✗ MQTT Error: {e}")


def run_cycle(config, session):
    """Runs one complete scraping and publishing cycle."""
    print(f"\n{'='*60}")
    print(f"STARTING NEW CYCLE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    val_mill_2 = scrape_device_data(session, DEVICE_MILL_2, "MILL_2")
    val_mill_1 = scrape_device_data(session, DEVICE_MILL_1, "MILL_1")
    
    if val_mill_1 and val_mill_2:
        publish_to_mqtt(config, val_mill_1, val_mill_2)
        return True
    else:
        print("\n" + "="*50)
        print("✗ ERROR: Could not scrape data for one or both devices.")
        print("="*50)
        print("Check the debug JSON files saved to disk for more information.")
        print("Files should be: debug_MILL_1_ajax.json and debug_MILL_2_ajax.json")
        return False


def main():
    """Main function to run the scraper and publisher in a continuous loop."""
    setup_debug_logging()
    config = load_config()
    
    print("\n" + "="*60)
    print("MQTT DATA PUBLISHER - CONTINUOUS MODE")
    print("="*60)
    print(f"Loop interval: {LOOP_INTERVAL} seconds")
    print(f"Press Ctrl+C to stop")
    print("="*60 + "\n")
    
    # Initial login
    session = login_to_site(config)
    if not session:
        print("✗ Initial login failed. Exiting.")
        sys.exit(1)
    
    cycle_count = 0
    
    try:
        while True:
            cycle_count += 1
            print(f"\n[Cycle #{cycle_count}]")
            
            # Run the scraping and publishing cycle
            success = run_cycle(config, session)
            
            # If the cycle failed, try to re-login
            if not success:
                print("\n⚠ Cycle failed. Attempting to re-login...")
                session = login_to_site(config)
                if not session:
                    print("✗ Re-login failed. Waiting before retry...")
            
            # Wait for the next cycle
            print(f"\n💤 Waiting {LOOP_INTERVAL} seconds until next cycle...")
            print(f"Next cycle at: {datetime.fromtimestamp(time.time() + LOOP_INTERVAL).strftime('%Y-%m-%d %H:%M:%S')}")
            time.sleep(LOOP_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n\n" + "="*60)
        print("SHUTDOWN REQUESTED")
        print("="*60)
        print(f"Total cycles completed: {cycle_count}")
        print("Exiting gracefully...")
        print("="*60 + "\n")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Unexpected error in main loop: {e}")
        print("Exiting...")
        sys.exit(1)


if __name__ == "__main__":
    main()