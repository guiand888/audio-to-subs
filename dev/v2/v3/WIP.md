# v3 features and refactoring

- modularity: bazarr integration can be disabled in the settings
  - In the Settings, "Bazarr Configuration" and "Media Path" are part of the same block
  - This is sort of an accordion menu as the entire Bazarr Integration section hides away if the integration is diabled
- Upload: Add an upload mode
  - it will have its own tab in the UI
  - it allows uploading video files into our application for on-demand transcription and subtitle creation
  - once the transcription is completed, the subtitle file can be downloaded from the UI
  - the UI also allows deleting the uploaded file and deleting the subtitle file that was created in this mode
- The "Wanted" entry in the sidebar is renamed "Bazarr" and appear only if the Bazarr integration is enabled
