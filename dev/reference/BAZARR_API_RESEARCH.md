# Bazarr API Research - Subtitle Automation Integration

**Date**: 2025-12-14
**Researcher**: Kilo Code
**Purpose**: Integration research for automated subtitle generation monitoring

## Executive Summary

Bazarr provides a comprehensive RESTful API that enables full monitoring and management of subtitle status across movies and TV episodes. This API can be leveraged to build an automation system that detects missing subtitles, tracks how long they've been missing, locates video files, and triggers subtitle generation when conditions are met.

## API Overview

### Base URL
```
http://bazarr:6767/api/
```

### Authentication
All endpoints require API key authentication via HTTP header:
```http
X-API-Key: your-bazarr-api-key
```

### API Namespaces
- **Subtitles**: Apply mods/tools to external subtitles
- **Subtitles Info**: Parse subtitle filenames and extract metadata
- **Movies Wanted**: List movies missing subtitles (KEY FOR AUTOMATION)
- **Episodes Wanted**: List TV episodes missing subtitles (KEY FOR AUTOMATION)
- **Files Browser**: Browse Bazarr's file system
- **History**: Access historical data about subtitle operations

## Key Endpoints for Automation

### 1. Wanted Subtitles Detection (PRIMARY)

#### Movies Missing Subtitles
```http
GET /api/movies/wanted
```

**Parameters:**
- `start` (int, optional): Paging start (default: 0)
- `length` (int, optional): Paging length (default: -1 for all)
- `radarrid[]` (int[], optional): Filter by specific Radarr IDs

**Response Structure:**
```json
{
  "data": [
    {
      "title": "Movie Title",
      "missing_subtitles": [
        {
          "name": "English",
          "code2": "en",
          "code3": "eng",
          "forced": false,
          "hi": false
        }
      ],
      "radarrId": 123,
      "sceneName": "Movie.Title.2023.1080p.BluRay.x264",
      "tags": ["action", "adventure"]
    }
  ],
  "total": 1
}
```

#### TV Episodes Missing Subtitles
```http
GET /api/episodes/wanted
```

**Parameters:**
- `start` (int, optional): Paging start (default: 0)
- `length` (int, optional): Paging length (default: -1 for all)
- `episodeid[]` (int[], optional): Filter by specific episode IDs

**Response Structure:**
```json
{
  "data": [
    {
      "seriesTitle": "Show Name",
      "episode_number": "1x01",
      "episodeTitle": "Pilot",
      "missing_subtitles": [
        {
          "name": "French",
          "code2": "fr",
          "code3": "fre",
          "forced": false,
          "hi": false
        }
      ],
      "sonarrSeriesId": 456,
      "sonarrEpisodeId": 789,
      "sceneName": "Show.Name.S01E01.1080p.BluRay.x264",
      "tags": ["comedy"],
      "seriesType": "standard"
    }
  ],
  "total": 1
}
```

### 2. File System Access

#### Browse Files
```http
GET /api/files
```

**Parameters:**
- `path` (string, optional): Path to browse (default: root)

**Response Structure:**
```json
[
  {
    "name": "Movies",
    "children": true,
    "path": "/movies"
  },
  {
    "name": "TV Shows",
    "children": true,
    "path": "/tv"
  }
]
```

### 3. Subtitle Information

#### Parse Subtitle Filenames
```http
GET /api/subtitles/info
```

**Parameters:**
- `filenames[]` (string[], required): Array of subtitle filenames

**Response Structure:**
```json
{
  "data": [
    {
      "filename": "Show.Name.S01E01.en.srt",
      "subtitle_language": "en",
      "season": 1,
      "episode": 1
    }
  ]
}
```

### 4. Subtitle Processing

#### Apply Mods/Tools to Subtitles
```http
PATCH /api/subtitles
```

**Parameters:**
- `action` (string, required): Action to perform (sync, translate, or mod name)
- `language` (string, required): Language code2
- `path` (string, required): Subtitles file path
- `type` (string, required): Media type (episode, movie)
- `id` (int, required): Media ID
- `forced` (string, optional): Forced subtitles flag
- `hi` (string, optional): Hearing impaired flag
- `reference` (string, optional): Reference for sync
- `max_offset_seconds` (string, optional): Max offset for sync

## Automation Implementation Strategy

### 1. Detection Logic

```python
import requests
import time
from datetime import datetime
from typing import Dict, List, Optional

class BazarrMonitor:
    def __init__(self, bazarr_url: str, api_key: str):
        self.bazarr_url = bazarr_url.rstrip('/')
        self.api_key = api_key
        self.headers = {'X-API-Key': api_key}
        
    def get_missing_subtitles(self) -> Dict[str, List[Dict]]:
        """Get all movies and episodes missing subtitles"""
        
        # Get movies missing subtitles
        movies_response = requests.get(
            f'{self.bazarr_url}/api/movies/wanted',
            headers=self.headers,
            params={'length': -1}  # Get all
        )
        movies_response.raise_for_status()
        
        # Get episodes missing subtitles
        episodes_response = requests.get(
            f'{self.bazarr_url}/api/episodes/wanted',
            headers=self.headers,
            params={'length': -1}  # Get all
        )
        episodes_response.raise_for_status()
        
        return {
            'movies': movies_response.json()['data'],
            'episodes': episodes_response.json()['data']
        }
```

### 2. Age Tracking

```python
class SubtitleAgeTracker:
    def __init__(self, state_file: str = 'subtitle_state.json'):
        self.state_file = state_file
        self.state = self._load_state()
        
    def _load_state(self) -> Dict:
        """Load tracking state from file"""
        try:
            with open(self.state_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {'movies': {}, 'episodes': {}}
        
    def _save_state(self):
        """Save tracking state to file"""
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)
        
    def track_missing_subtitles(self, missing_items: Dict[str, List[Dict]]):
        """Track when subtitles were first detected as missing"""
        now = datetime.now().isoformat()
        
        # Track movies
        for movie in missing_items['movies']:
            movie_id = str(movie['radarrId'])
            if movie_id not in self.state['movies']:
                self.state['movies'][movie_id] = {
                    'first_detected': now,
                    'title': movie['title'],
                    'missing_languages': [lang['code2'] for lang in movie['missing_subtitles']]
                }
        
        # Track episodes
        for episode in missing_items['episodes']:
            episode_id = str(episode['sonarrEpisodeId'])
            if episode_id not in self.state['episodes']:
                self.state['episodes'][episode_id] = {
                    'first_detected': now,
                    'series_title': episode['seriesTitle'],
                    'episode_number': episode['episode_number'],
                    'episode_title': episode['episodeTitle'],
                    'missing_languages': [lang['code2'] for lang in episode['missing_subtitles']]
                }
        
        self._save_state()
        
    def get_subtitle_age(self, item_id: str, item_type: str = 'movie') -> Optional[float]:
        """Get how long subtitles have been missing in hours"""
        if item_type == 'movie':
            item = self.state['movies'].get(item_id)
        else:
            item = self.state['episodes'].get(item_id)
            
        if item and 'first_detected' in item:
            first_detected = datetime.fromisoformat(item['first_detected'])
            age = datetime.now() - first_detected
            return age.total_seconds() / 3600  # Hours
            
        return None
```

### 3. Video File Location Resolution

```python
def get_video_file_path(item: Dict, item_type: str) -> Optional[str]:
    """Get the video file path for a movie or episode"""
    
    # First try to get from sceneName (often contains path info)
    scene_name = item.get('sceneName', '')
    
    # If sceneName doesn't contain path, use files browser API
    if not scene_name or not any(char in scene_name for char in ['/', '\\']):
        # This would need integration with Sonarr/Radarr APIs
        # or additional Bazarr API calls to resolve paths
        return None
        
    return scene_name
```

### 4. Complete Automation Workflow

```python
class SubtitleAutomation:
    def __init__(self, bazarr_url: str, api_key: str):
        self.bazarr = BazarrMonitor(bazarr_url, api_key)
        self.tracker = SubtitleAgeTracker()
        self.subtitle_generator = YourSubtitleGenerator()  # Your implementation
        
    def monitor_and_generate(self, min_age_hours: float = 24.0):
        """Monitor for missing subtitles and generate if conditions met"""
        
        # Get all missing subtitles
        missing_items = self.bazarr.get_missing_subtitles()
        
        # Track age of missing subtitles
        self.tracker.track_missing_subtitles(missing_items)
        
        # Process movies
        for movie in missing_items['movies']:
            movie_id = str(movie['radarrId'])
            age_hours = self.tracker.get_subtitle_age(movie_id, 'movie')
            
            if age_hours and age_hours >= min_age_hours:
                video_path = get_video_file_path(movie, 'movie')
                if video_path:
                    print(f"Generating subtitles for movie: {movie['title']}")
                    print(f"Missing languages: {[lang['code2'] for lang in movie['missing_subtitles']]}")
                    print(f"Video path: {video_path}")
                    print(f"Missing for: {age_hours:.1f} hours")
                    
                    # Generate subtitles using your pipeline
                    # self.subtitle_generator.generate(video_path, target_languages)
                    
                    # After generation, you could optionally:
                    # 1. Use Bazarr's subtitle processing API to apply mods
                    # 2. Trigger a rescan in Bazarr
                    # 3. Update your tracking state
        
        # Process episodes (similar logic)
        for episode in missing_items['episodes']:
            episode_id = str(episode['sonarrEpisodeId'])
            age_hours = self.tracker.get_subtitle_age(episode_id, 'episode')
            
            if age_hours and age_hours >= min_age_hours:
                video_path = get_video_file_path(episode, 'episode')
                if video_path:
                    print(f"Generating subtitles for episode: {episode['seriesTitle']} {episode['episode_number']}")
                    print(f"Missing languages: {[lang['code2'] for lang in episode['missing_subtitles']]}")
                    print(f"Video path: {video_path}")
                    print(f"Missing for: {age_hours:.1f} hours")
                    
                    # Generate subtitles using your pipeline
                    # self.subtitle_generator.generate(video_path, target_languages)
```

### 5. Scheduled Monitoring

```python
def run_scheduled_monitoring(bazarr_url: str, api_key: str, interval_hours: float = 6.0):
    """Run monitoring on a schedule"""
    automation = SubtitleAutomation(bazarr_url, api_key)
    
    print(f"Starting Bazarr subtitle automation monitor (interval: {interval_hours} hours)")
    
    while True:
        try:
            print(f"\n{'='*50}")
            print(f"Running monitoring cycle: {datetime.now()}")
            print('='*50)
            
            automation.monitor_and_generate()
            
            # Sleep until next cycle
            sleep_seconds = interval_hours * 3600
            print(f"Next cycle in {interval_hours} hours...")
            time.sleep(sleep_seconds)
            
        except KeyboardInterrupt:
            print("Monitoring stopped by user")
            break
        except Exception as e:
            print(f"Error during monitoring: {e}")
            # Wait before retrying
            time.sleep(60)

if __name__ == "__main__":
    # Configuration
    BAZARR_URL = "http://localhost:6767"
    BAZARR_API_KEY = "your-api-key-here"
    
    # Run with 6-hour monitoring interval
    run_scheduled_monitoring(BAZARR_URL, BAZARR_API_KEY, interval_hours=6.0)
```

## Error Handling Considerations

### Common Error Scenarios

1. **Authentication Failure**: Invalid API key
2. **Network Issues**: Bazarr instance unavailable
3. **Rate Limiting**: Too many API requests
4. **Path Mapping**: Video paths not accessible
5. **Permission Issues**: Cannot read/write files

### Recommended Error Handling

```python
def safe_api_call(self, endpoint: str, **kwargs):
    """Make API call with proper error handling"""
    try:
        response = requests.get(
            f'{self.bazarr_url}{endpoint}',
            headers=self.headers,
            **kwargs
        )
        
        if response.status_code == 401:
            raise AuthenticationError("Invalid Bazarr API key")
        elif response.status_code == 404:
            raise NotFoundError(f"Endpoint {endpoint} not found")
        elif response.status_code == 429:
            raise RateLimitError("API rate limit exceeded")
        elif response.status_code >= 500:
            raise ServerError(f"Bazarr server error: {response.status_code}")
            
        response.raise_for_status()
        return response
        
    except requests.exceptions.RequestException as e:
        raise APIConnectionError(f"Failed to connect to Bazarr: {e}")
```

## Integration with Existing Systems

### Sonarr/Radarr Integration

For complete path resolution, consider integrating with:

1. **Sonarr API**: Get episode file paths
2. **Radarr API**: Get movie file paths
3. **File System Access**: Direct path resolution

### Example Sonarr Integration

```python
def get_episode_path_from_sonarr(sonarr_url: str, sonarr_api_key: str, episode_id: int) -> Optional[str]:
    """Get episode file path from Sonarr API"""
    try:
        response = requests.get(
            f'{sonarr_url}/api/episode/{episode_id}',
            headers={'X-Api-Key': sonarr_api_key}
        )
        response.raise_for_status()
        data = response.json()
        return data.get('path')
    except Exception as e:
        print(f"Error getting episode path from Sonarr: {e}")
        return None
```

## Performance Optimization

### Caching Strategies

1. **Response Caching**: Cache API responses for short periods
2. **State Persistence**: Use efficient storage for tracking state
3. **Batch Processing**: Process multiple items in parallel
4. **Rate Limiting**: Respect API rate limits

### Example Caching

```python
from functools import lru_cache

@lru_cache(maxsize=100)
def get_movie_details(self, movie_id: int) -> Optional[Dict]:
    """Get movie details with caching"""
    try:
        response = requests.get(
            f'{self.bazarr_url}/api/movies/{movie_id}',
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error getting movie details: {e}")
        return None
```

## Security Considerations

### API Key Management

1. **Environment Variables**: Store API keys securely
2. **Secret Management**: Use tools like Podman secrets
3. **Minimal Permissions**: Use least-privilege API keys
4. **Rotation**: Regularly rotate API keys

### Example Secure Configuration

```python
import os
from dotenv import load_dotenv

# Load from .env file or environment
load_dotenv()

BAZARR_API_KEY = os.getenv('BAZARR_API_KEY')
if not BAZARR_API_KEY:
    raise ValueError("BAZARR_API_KEY environment variable not set")
```

## Deployment Options

### 1. Standalone Service

Run as a separate service with scheduled monitoring:
```bash
python bazarr_monitor.py
```

### 2. Containerized Deployment

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY . .

RUN pip install requests python-dotenv

CMD ["python", "bazarr_monitor.py"]
```

### 3. Systemd Service

```ini
[Unit]
Description=Bazarr Subtitle Automation Monitor
After=network.target

[Service]
User=bazarr
ExecStart=/usr/bin/python3 /opt/bazarr_monitor/bazarr_monitor.py
Restart=always
RestartSec=60
Environment=BAZARR_API_KEY=your-api-key

[Install]
WantedBy=multi-user.target
```

## Future Enhancements

### 1. Webhook Integration

- Listen for Bazarr webhooks instead of polling
- Real-time event-driven processing
- Reduced API load

### 2. Advanced Filtering

- Filter by tags, quality profiles
- Exclude specific languages
- Priority-based processing

### 3. Notification System

- Email/SMS notifications for generation results
- Integration with notification services
- Detailed logging and reporting

### 4. Multi-language Support

- Generate multiple languages per video
- Language-specific quality settings
- Fallback language chains

## Conclusion

The Bazarr API provides a robust foundation for building an automated subtitle generation system. By leveraging the `wanted` endpoints, you can:

1. ✅ **Detect missing subtitles** across all movies and episodes
2. ✅ **Track how long subtitles have been missing** using state tracking
3. ✅ **Locate video files** through scene names and file browser API
4. ✅ **Trigger generation** when your conditions are met
5. ✅ **Integrate seamlessly** with your existing subtitle generation pipeline

The implementation strategy outlined above provides a complete blueprint for building this automation system with proper error handling, performance optimization, and security considerations. The system should focus on proper language code implementation in filenames to ensure compatibility with Bazarr's expected naming conventions.