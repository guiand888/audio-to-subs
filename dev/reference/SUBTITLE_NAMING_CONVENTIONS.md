# Subtitle File Naming Conventions Research

**Date**: 2025-12-15
**Researcher**: Kilo Code
**Purpose**: Document subtitle naming conventions for Bazarr compatibility and video player standards

## Executive Summary

This document outlines the subtitle file naming conventions used by Bazarr and widely supported by video players. Proper naming ensures subtitles are automatically detected and associated with the correct video files.

## Bazarr Subtitle Naming Conventions

Based on research of the Bazarr subtitle management system, the following naming patterns are used and recognized by most video players:

### Standard Format

```
Video.Filename.Language.Code.srt
```

Where:
- `Video.Filename` - The base name of the video file (without extension)
- `Language.Code` - 2 or 3 letter language code (ISO 639-1 or ISO 639-2)
- `.srt` - Subtitle file extension

### Examples

```
Movie.Title.2023.1080p.BluRay.x264.en.srt
Show.Name.S01E01.1080p.BluRay.x264.fr.srt
Documentary.Name.2024.720p.WebRip.x264.es.srt
```

### Language Codes

Common language codes supported:

| Language | ISO 639-1 (2-letter) | ISO 639-2 (3-letter) |
|----------|----------------------|----------------------|
| English | en | eng |
| French | fr | fra/fre |
| Spanish | es | spa |
| German | de | deu/ger |
| Italian | it | ita |
| Portuguese | pt | por |
| Russian | ru | rus |
| Chinese | zh | zho |
| Japanese | ja | jpn |
| Korean | ko | kor |

### Multi-language Support

For multiple subtitle languages for the same video:

```
Movie.Title.2023.en.srt
Movie.Title.2023.fr.srt
Movie.Title.2023.es.srt
```

### Forced Subtitles

Forced subtitles (only for foreign language parts) use `.forced` suffix:

```
Movie.Title.2023.en.forced.srt
```

### Hearing Impaired Subtitles

Subtitles for the hearing impaired use `.hi` suffix:

```
Movie.Title.2023.en.hi.srt
```

## Video Player Compatibility

These naming conventions are widely supported by popular media players:

### Supported Players

- **Plex** - Automatic subtitle detection and selection
- **Jellyfin** - Full subtitle naming support
- **Emby** - Recognizes standard naming patterns
- **Kodi** - Supports all common subtitle naming conventions
- **VLC** - Automatic subtitle loading
- **MPV** - Recognizes subtitle files with matching base names
- **Windows Media Player** - Basic subtitle support
- **QuickTime Player** - Limited subtitle support

### Player-Specific Notes

#### Plex/Jellyfin/Emby
These media servers use the following priority for subtitle detection:
1. Exact filename match with language code
2. Filename match without language code
3. Any subtitle file in the same directory

#### Kodi
Kodi supports advanced subtitle naming with these patterns:
- `moviename.cd1.en.srt` (for multi-CD movies)
- `moviename.en.forced.srt` (forced subtitles)
- `moviename.en.hi.srt` (hearing impaired)

#### VLC/MPV
These players automatically load subtitles with:
- Same base filename as video
- Language code suffixes
- Files in the same directory

## Implementation Requirements

### Current System Analysis

The current `audio-to-subs` system generates subtitle files with basic naming:
```
output.srt
```

### Required Enhancements

1. **Language Code Support** - Add language codes to generated filenames
2. **Video Filename Matching** - Match subtitle names to source video filenames
3. **Proper Language Code Inclusion** - Ensure language codes are properly included in filenames
4. **Bazarr Compatibility** - Ensure generated filenames match Bazarr expectations

### Implementation Plan

#### Phase 1: Basic Language Support
- [ ] Add `--language` parameter to CLI for language specification
- [ ] Modify subtitle generator to include language codes in filenames
- [ ] Update file naming logic in `subtitle_generator.py`
- [ ] Ensure proper language code format (ISO 639-1/2)

#### Phase 2: Advanced Naming
- [ ] Implement video filename parsing and matching
- [ ] Ensure generated filenames include proper language code suffixes
- [ ] Support single language generation with proper naming
- [ ] Ensure compatibility with major media players

#### Phase 3: Bazarr Integration
- [ ] Ensure generated filenames match Bazarr expectations
- [ ] Add Bazarr-compatible naming validation
- [ ] Test with actual Bazarr instances

## Testing Requirements

### Test Cases

1. **Basic Language Naming**
   - Input: `movie.mp4` with `--language en`
   - Output: `movie.en.srt`

2. **Single Language Generation**
   - Input: `show.s01e01.mp4` with `--language fr`
   - Output: `show.s01e01.fr.srt`

3. **Complex Filenames**
   - Input: `Movie.Title.2023.1080p.BluRay.x264.mp4` with `--language es`
   - Output: `Movie.Title.2023.1080p.BluRay.x264.es.srt`

4. **Language Code Validation**
   - Input: `video.mp4` with `--language en`
   - Output: `video.en.srt` (proper ISO 639-1 format)

5. **Filename Matching**
   - Input: `Documentary.Name.2024.720p.WebRip.x264.mp4` with `--language de`
   - Output: `Documentary.Name.2024.720p.WebRip.x264.de.srt`

## Industry Standards Compliance

The proposed naming conventions comply with:

1. **ISO 639-1/2** - Standard language codes
2. **Matroska/MP4** - Common subtitle naming in container formats
3. **Plex Media Server** - Official naming guidelines
4. **Kodi/XBMC** - Documented subtitle naming patterns
5. **Bazarr** - Expected subtitle file naming

## Future Considerations

### Additional Features

1. **Custom Naming Templates** - Allow users to define their own patterns
2. **Subtitle Format Detection** - Auto-detect best format (SRT/VTT/SSA)
3. **Character Set Handling** - Ensure proper encoding for all languages
4. **Fallback Languages** - Automatic fallback language selection

### Integration Points

1. **Bazarr API** - Direct subtitle upload and registration
2. **Media Server APIs** - Automatic library updates after generation
3. **File System Monitoring** - Watch directories for new videos needing subtitles

## References

1. [Plex Subtitle Naming Guide](https://support.plex.tv/articles/200471133-adding-local-subtitles/)
2. [Kodi Subtitle Documentation](https://kodi.wiki/view/Subtitles)
3. [Bazarr Documentation](https://github.com/morpheus65535/bazarr/wiki)
4. [ISO 639 Language Codes](https://www.loc.gov/standards/iso639-2/php/code_list.php)

## Conclusion

Implementing proper subtitle naming conventions will:
- ✅ Ensure compatibility with Bazarr and major media players
- ✅ Enable automatic subtitle detection and selection
- ✅ Include proper language codes in filenames
- ✅ Follow industry standards and best practices
- ✅ Improve user experience with generated subtitles

The implementation should be prioritized to ensure generated subtitles work seamlessly with existing media management ecosystems, with a focus on proper language code inclusion and filename compliance.