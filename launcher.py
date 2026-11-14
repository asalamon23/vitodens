import os
import sys
import threading
import time
import webbrowser

if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

from app import app, scheduler, execute_scheduled


def open_dashboard():
    time.sleep(2)
    webbrowser.open('http://127.0.0.1:5000')

if __name__ == '__main__':
    if not os.environ.get('VIESSMANN_CLIENT_ID'):
        print('VIESSMANN_CLIENT_ID is not set. Demo UI may load but boiler login cannot work.')
    scheduler.start(execute_scheduled)
    threading.Thread(target=open_dashboard, daemon=True).start()
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
