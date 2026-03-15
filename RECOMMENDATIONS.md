# Instagram Workflow - Recommendations & Improvements

Based on analysis of the YouTube workflow, here are key recommendations to enhance the Instagram workflow:

## 🎯 Critical Improvements

### 1. **Background Media Integration** ⚠️ HIGH PRIORITY

**Current Issue:** The workflow uses placeholder URLs for background media:
```python
modifications[f"Background-Media-{scene_num}.source"] = f"https://example.com/placeholder/..."
```

**Recommendation:** Integrate stock footage/image APIs:

**Option A: Pexels API (Free)**
```python
# Add to requirements.txt: pexels-api
import requests

def get_pexels_video(keyword: str) -> str:
    """Get stock video from Pexels API."""
    headers = {"Authorization": "YOUR_PEXELS_API_KEY"}
    response = requests.get(
        f"https://api.pexels.com/videos/search?query={keyword}&per_page=1",
        headers=headers
    )
    if response.status_code == 200:
        videos = response.json().get("videos", [])
        if videos:
            return videos[0]["video_files"][0]["link"]
    return None
```

**Option B: Unsplash API (Free for images)**
```python
def get_unsplash_image(keyword: str) -> str:
    """Get stock image from Unsplash API."""
    response = requests.get(
        f"https://api.unsplash.com/photos/random?query={keyword}&client_id=YOUR_KEY"
    )
    if response.status_code == 200:
        return response.json()["urls"]["regular"]
    return None
```

**Option C: AI Image Generation (DALL-E/Gemini)**
- Copy `generate_visuals.py` from YouTube workflow
- Generate images based on `background_keyword` from script

### 2. **Error Handling & Retry Logic** 🔄

**Current Issue:** Limited error handling in script generation.

**Recommendation:** Add comprehensive retry logic:
```python
# Enhanced error handling
def generate_script_with_retry(story: str, topic: str, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            result = generate_script_with_openai(story, topic)
            if result["success"]:
                return result
        except openai.RateLimitError:
            wait_time = 2 ** attempt  # Exponential backoff
            print(f"Rate limit hit. Waiting {wait_time}s...")
            time.sleep(wait_time)
        except openai.APIError as e:
            if attempt == max_retries - 1:
                return {"success": False, "error": str(e)}
            time.sleep(2)
    return {"success": False, "error": "Max retries exceeded"}
```

### 3. **Asset Upload to Cloud Storage** ☁️

**Current Issue:** No mechanism to upload generated assets (images, audio) to public storage.

**Recommendation:** Add GCS upload capability (copy from YouTube workflow):
- Copy `execution/upload_to_gcs.py` from YouTube workflow
- Upload images/audio before passing to Creatomate
- Use public URLs instead of local files

### 4. **Template Element Name Detection** 🔍

**Current Issue:** Hardcoded element names might not match your Creatomate template.

**Recommendation:** Add template inspection:
```python
def get_template_elements(template_id: str) -> dict:
    """Fetch template structure from Creatomate API."""
    response = requests.get(
        f"{CREATOMATE_API_URL}/templates/{template_id}",
        headers={"Authorization": f"Bearer {CREATOMATE_API_KEY}"}
    )
    if response.status_code == 200:
        # Parse template structure to find element names
        template_data = response.json()
        # Extract element names from template
        return extract_element_names(template_data)
    return None
```

### 5. **ElevenLabs Integration Format** 🎙️

**Current Issue:** Multiple format attempts might cause confusion.

**Recommendation:** Standardize on Creatomate's ElevenLabs format:
```python
# Based on plan.md, use this format:
modifications[f"Voiceover-{scene_num}.source"] = "elevenlabs"
modifications[f"Voiceover-{scene_num}.settings"] = {
    "text": voiceover_content,
    "voice_id": ELEVENLABS_VOICE_ID,
    "api_key": ELEVENLABS_API_KEY
}
```

**OR** if Creatomate template is pre-configured with ElevenLabs:
```python
# Just pass text directly (simpler)
modifications[f"Voiceover-{scene_num}"] = voiceover_content
```

### 6. **Scene Duration Management** ⏱️

**Current Issue:** No duration calculation for scenes.

**Recommendation:** Add duration estimation:
```python
def estimate_scene_duration(text: str) -> float:
    """Estimate scene duration based on text length."""
    words_per_minute = 150  # Average speaking rate
    word_count = len(text.split())
    duration = (word_count / words_per_minute) * 60
    return max(duration, 3.0)  # Minimum 3 seconds
```

### 7. **Better Logging & Progress Tracking** 📊

**Recommendation:** Add structured logging:
```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('workflow.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)
```

## 🚀 Feature Enhancements

### 8. **Add Visual Generation Stage**

Copy `generate_visuals.py` from YouTube workflow to generate images for each scene:
- Use OpenAI DALL-E or Gemini
- Generate images based on `background_keyword`
- Upload to GCS before passing to Creatomate

### 9. **Add Video Preview/Review**

Before final render, create a preview:
- Generate thumbnail for each scene
- Show script + visuals preview
- Allow manual review/editing

### 10. **Batch Processing**

Add ability to process multiple topics:
```python
def batch_generate(topics: list[str]):
    """Generate videos for multiple topics."""
    results = []
    for topic in topics:
        result = run_full_workflow(topic)
        results.append(result)
    return results
```

## 📋 Implementation Priority

1. **HIGH:** Background media integration (Pexels/Unsplash/AI)
2. **HIGH:** Error handling & retry logic
3. **MEDIUM:** Asset upload to cloud storage
4. **MEDIUM:** Template element detection
5. **LOW:** Batch processing
6. **LOW:** Preview/review system

## 🔧 Quick Wins

### Immediate Fixes (30 minutes):

1. **Fix placeholder URLs:**
   ```python
   # Replace placeholder with actual stock media
   background_url = get_pexels_video(background_keyword) or get_unsplash_image(background_keyword)
   ```

2. **Add better error messages:**
   ```python
   except Exception as e:
       logger.error(f"Script generation failed: {type(e).__name__}: {str(e)}")
       return {"success": False, "error": f"{type(e).__name__}: {str(e)}"}
   ```

3. **Validate script structure:**
   ```python
   def validate_script(script: dict) -> bool:
       """Validate script has required fields."""
       required = ["scenes", "title"]
       if not all(key in script for key in required):
           return False
       if not script["scenes"] or len(script["scenes"]) != 5:
           return False
       return True
   ```

## 📚 Code to Copy from YouTube Workflow

1. `execution/upload_to_gcs.py` - For asset hosting
2. `execution/generate_visuals.py` - For AI image generation
3. Error handling patterns from `assemble_video.py`
4. Duration calculation logic from `assemble_video.py`

## 🎯 Next Steps

1. **Week 1:** Implement background media integration
2. **Week 2:** Add error handling & retry logic
3. **Week 3:** Integrate GCS upload for assets
4. **Week 4:** Add visual generation stage

---

**Note:** These recommendations are based on proven patterns from the YouTube workflow that have been tested and refined over time.
