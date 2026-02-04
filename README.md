# Hyde Park Compound Gate System

A Flask-based MVP for managing compound gate access using mobile ID card scanning and Vision LLM verification via OpenRouter.

## Features

- **Mobile-First UI**: Touch-friendly, tablet-optimized interface with Bootstrap 5
- **Camera-Based ID Scanning**: Capture Egyptian National ID cards using device camera
- **Vision LLM Extraction**: Extract name and 14-digit ID number using OpenRouter Vision API
- **Card-Centric Verification**: Automatic person registration and access control
- **Admin Panel**: Manage persons database and view entry logs
- **Block Management**: Block persons with custom reasons

## Tech Stack

- **Backend**: Flask 3.0.0
- **Database**: SQLite
- **Frontend**: Bootstrap 5 + Vanilla JavaScript
- **Camera**: getUserMedia() API
- **Vision API**: OpenRouter (qwen/qwen-vl-plus)

## Installation

1. Install dependencies:
```bash
pip3 install -r requirements.txt
```

2. Set OpenRouter API key:
```bash
export OPENROUTER_API_KEY="your_api_key_here"
```

3. Run the application:
```bash
python3 app.py
```

4. Access the application:
```
http://0.0.0.0:5000
```

## Project Structure

```
hyde_park_gate/
├── app.py                  # Main Flask application
├── database.py             # Database operations
├── requirements.txt        # Python dependencies
├── gate_system.db         # SQLite database (auto-created)
├── templates/
│   ├── home.html          # Home page with Security/Admin buttons
│   ├── security.html      # Security screen with ID scanner
│   └── admin.html         # Admin panel
├── static/
│   ├── js/
│   │   └── camera.js      # Camera capture and verification logic
│   └── captures/          # Captured ID card images
└── README.md
```

## Core Flow

### Home Page (`/`)
- Two large buttons: **Security** and **Admin**
- Responsive, touch-friendly interface

### Security Screen (`/security`)
- **SCAN ID CARD** button opens camera with overlay frame
- Captures image and sends to backend for verification
- Vision LLM extracts name and 14-digit ID number
- Shows appropriate response based on verification result

### Verification Logic (`/verify`)

1. **New Person** (ID not in database):
   - Auto-create person record
   - Insert entry with status `NEW`
   - Show green toast: "✓ Welcome, [Name]! Entry recorded."

2. **Existing Person - Active** (ID exists, not blocked):
   - Insert entry with status `ALLOWED`
   - Show green toast: "✓ [Name] – Access granted."

3. **Existing Person - Blocked** (ID exists, is_blocked=1):
   - Do NOT insert entry
   - Show blocking modal with name, ID, and reason

4. **Invalid Card** (ID not readable):
   - Show red toast: "❌ Could not read ID card. Please rescan."

### Admin Screen (`/admin`)
- **Persons Table**: View all registered persons with status and block actions
- **Entries Log**: View recent entry records with timestamps
- **Block Action**: Block persons with optional custom reason

## Database Schema

### `persons` Table
- `id_number` (TEXT PRIMARY KEY): 14-digit Egyptian National ID
- `name` (TEXT): Full name from ID card
- `is_blocked` (INTEGER): 0 = Active, 1 = Blocked
- `block_reason` (TEXT): Reason for blocking

### `entries` Table
- `id` (INTEGER PRIMARY KEY AUTOINCREMENT)
- `name` (TEXT): Person's name
- `id_number` (TEXT): Person's ID number
- `status` (TEXT): `NEW` or `ALLOWED`
- `timestamp` (DATETIME): Entry timestamp

## OpenRouter Integration

The system uses OpenRouter's Vision API to extract information from ID cards:

- **Endpoint**: `https://openrouter.ai/api/v1/chat/completions`
- **Model**: `qwen/qwen-vl-plus` (or any vision model)
- **Input**: Base64-encoded JPEG image
- **Output**: JSON with `name` and `id_number` fields

### Extraction Prompt
```
You are reading an Egyptian National ID card.
Extract:
- Full name
- 14-digit national ID number

Return JSON only: { "name": "", "id_number": "" }
If the ID is unreadable, return { "id_number": "NOT_FOUND" }
```

## Configuration

- **Port**: 5000 (configurable in `app.py`)
- **Host**: 0.0.0.0 (accessible from network)
- **Debug Mode**: Enabled (disable for production)
- **Captures Directory**: `static/captures/`

## Security Notes

- No authentication implemented (MVP only)
- API key should be stored securely in production
- HTTPS recommended for production deployment
- Camera permissions required on client device

## Browser Compatibility

- Modern browsers with getUserMedia() support
- Tested on Chrome, Safari, Firefox
- Mobile-optimized for tablets and smartphones

## License

MIT License
