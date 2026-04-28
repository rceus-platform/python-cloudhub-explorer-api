# CloudHub Explorer API

## Overview

The **CloudHub Explorer API** is a high-performance, unified backend service designed to orchestrate file management across multiple cloud storage providers. Built with **FastAPI** and **Python 3.11**, it provides a centralized interface for browsing, searching, and streaming media from services like **Google Drive** and **MEGA**.

This API serves as the backbone for the [CloudHub Explorer UI](https://github.com/rceus-platform/react-cloudhub-explorer-ui), enabling multi-account management and high-speed media delivery with range-request support.

## Key Features

### 🌐 Unified Cloud Integration
- **Multi-Provider Support**: Seamlessly browse files from Google Drive and MEGA in a single consolidated view.
- **Folder Merging**: Advanced logic to merge directory structures from different providers into a unified virtual filesystem.

### 👥 Multi-Account Management
- **Parallel Connections**: Connect multiple accounts per provider (e.g., 5+ MEGA accounts, 10+ Google Drive accounts) simultaneously.
- **OAuth & Credential Management**: Secure handling of Google OAuth2 flows and MEGA session persistence.

### 🎬 Media Streaming Engine
- **Range-Request Support**: High-performance streaming for large video files, allowing instant seeking and smooth playback.
- **Node.js Sidecar Integration**: Leverages a specialized Node.js service for high-speed MEGA file streaming.

### 🚀 Node.js Sidecar Integration
The CloudHub Explorer API utilizes a specialized Node.js sidecar for high-performance streaming, particularly for providers like MEGA where Python-based streaming can be bottlenecked by CPU-intensive decryption.

#### Prerequisites
- **Node.js**: Version 16 or higher is required.

#### Installation
1. Navigate to the sidecar directory (typically in a sibling repo or designated folder):
   ```bash
   git clone https://github.com/rceus-platform/node-mega-stream-service
   cd node-mega-stream-service
   npm install
   ```
2. Build the service (if applicable):
   ```bash
   npm run build
   ```

#### Configuration
Required environment variables for the sidecar:
- `SIDE_CAR_PORT`: Port the sidecar listens on (default: `4000`)
- `SIDE_CAR_HOST`: Host for the sidecar (default: `localhost`)

#### Startup
Launch the sidecar alongside the Python API:
```bash
# Start the sidecar
npm start

# Or using node directly
node ./dist/index.js
```

For production, it is recommended to run the sidecar via `systemd` or as a service in `docker-compose`.

### 🛡️ Security & Performance
- **Passcode Protection**: Unified access control layer via `SITE_PASSCODE`.
- **Database Caching**: Persistent metadata caching using SQLAlchemy and SQLite for lightning-fast file lookups.

## Tech Stack

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/)
- **Runtime**: [Python 3.11+](https://www.python.org/)
- **Package Manager**: [uv](https://github.com/astral-sh/uv)
- **Database**: SQLite with [SQLAlchemy 2.0](https://www.sqlalchemy.org/)
- **Validation**: [Pydantic v2](https://docs.pydantic.dev/)
- **Cloud SDKs**: `google-api-python-client`, `mega.py`

## Project Structure

```text
application-source/
├── app/
│   ├── api/          # API Route definitions (auth, accounts, files)
│   ├── core/         # Global config, security, and dependencies
│   ├── db/           # Database models, schemas, and session management
│   ├── services/     # Cloud provider specific logic (GDrive, Mega)
│   ├── utils/        # Shared utilities (folder merging, file helpers)
│   └── main.py       # Application entry point & middleware config
├── tests/            # Pytest suite for API and service validation
├── pyproject.toml    # Project dependencies and tool configuration
└── uv.lock           # Deterministic dependency lockfile
```

## Getting Started

### Prerequisites

- **Python**: 3.11 or higher
- **uv**: Astral's high-speed Python package manager

### Installation

1. Clone the repository and navigate to the application directory:
   ```bash
   cd python-cloudhub-explorer-api/application-source
   ```

2. Sync dependencies using `uv`:
   ```bash
   uv sync
   ```

### Configuration

Create a `.env` file in the `application-source` directory:

```env
SITE_PASSCODE=8080
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret

# Optional: Default MEGA credentials for environment-based login
MEGA_USERNAME=your_mega_email
MEGA_PASSWORD=your_mega_password
```

### Running the API

Start the development server with hot-reload:

```bash
uv run uvicorn app.main:app --reload --port 8000
```

The API documentation (Swagger UI) will be available at `http://localhost:8000/docs`.

## API Endpoints

| Category | Endpoint | Description |
|----------|----------|-------------|
| **Auth** | `POST /auth/login` | Authenticate and retrieve session tokens |
| **Accounts** | `GET /accounts/google/login` | Initiate Google OAuth flow |
| **Accounts** | `POST /accounts/mega/login` | Connect a new MEGA account |
| **Files** | `GET /files/` | List files from all connected accounts |
| **Files** | `GET /files/stream` | Stream file content with range support |

---

Built with precision for the modern cloud explorer.
