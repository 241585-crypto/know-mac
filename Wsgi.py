import os
# Set your Google API key here
os.environ['GOOGLE_API_KEY'] = 'AIzaSyCFUJCJI0Fm_4GSvV2cnITX-yHm801ijJc'
# Set your base URL here
os.environ['BASE_URL'] = 'https://bmw.pythonanywhere.com'

import sys
sys.path.insert(0, '/home/BMW/know-mac')
from server import app as application
