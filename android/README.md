# Job Engine Android app

This is a native Kotlin/Jetpack Compose client for the existing FastAPI backend. It does not run the Python backend
on the phone. Start the backend on a computer or server that the phone can reach, then configure its URL in Settings.

## Run from Android Studio

1. Open this `android/` directory in Android Studio and allow Gradle sync.
2. Run the `app` configuration on an emulator or Android device.
3. Start the Python backend separately. For the Android emulator, use `http://10.0.2.2:8000`. For a physical phone,
   run `uvicorn main:app --host 0.0.0.0 --port 8000`, allow it through the computer's firewall, and use the computer's
   LAN address, such as `http://192.168.1.20:8000`.
4. Configure the profile in the backend's web interface. In the app, enter the backend URL and, if configured, HTTP
   Basic Auth credentials. The app keeps the password in memory only.

The app can add jobs, view scored matches, approve/reject matches, prepare application packets, update application
statuses, open job pages, and request the optional AI review from the backend. AI review requires the backend's
`requirements-ai.txt` dependencies and an `OPENAI_API_KEY` on the backend.

The app permits cleartext HTTP for local development. Use HTTPS before connecting over a shared network.
