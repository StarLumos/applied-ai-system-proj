import os
import tempfile

# Send the app's log file to a throwaway folder so test runs never write to the real logs/.
# Set at import time: the Streamlit app configures logging as soon as AppTest runs it.
os.environ.setdefault("PAWPAL_LOG_DIR", tempfile.mkdtemp(prefix="pawpal-test-logs-"))
