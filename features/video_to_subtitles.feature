Feature: Convert video to subtitles
  As a user
  I want to convert video audio to SRT subtitles
  So that I can watch videos with captions

  Scenario: Successfully convert video to subtitles
    Given I have a video file "test_video.mp4"
    And I have a valid Mistral API key
    When I process the video with audio-to-subs
    Then I should get an SRT subtitle file
    And the SRT file should contain valid timestamps
    And the SRT file should contain transcribed text

  Scenario: Handle missing video file
    Given I do not have a video file
    When I try to process a non-existent video
    Then I should get an error message
    And the error message should say "file not found"
    And no output file should be created

  Scenario: Handle missing API key
    Given I have a video file "test_video.mp4"
    And I do not have a Mistral API key
    When I try to process the video
    Then I should get an error message
    And the error message should mention API key
    And no output file should be created

  Scenario: Extract audio from various video formats
    Given I have video files of different formats:
      | format |
      | mp4    |
      | mkv    |
      | avi    |
      | mov    |
    When I extract audio from each video
    Then all audio extractions should succeed
    And each audio file should be in WAV format
    And each audio file should have correct sample rate (16kHz)

  Scenario: Generate valid SRT format
    Given I have transcription segments:
      | start | end  | text              |
      | 0.0   | 2.5  | Hello world       |
      | 2.5   | 5.0  | This is a test    |
      | 5.0   | 7.5  | SRT format works  |
    When I generate SRT subtitles
    Then the output file should be valid SRT format
    And each subtitle should have an index
    And each subtitle should have start and end timestamps
    And each subtitle should have the correct text
    And subtitles should be separated by blank lines

  Scenario: Handle transcription API errors
    Given I have a video file "test_video.mp4"
    And the Mistral API is unavailable
    When I try to process the video
    Then I should get a transcription error
    And the error message should indicate API failure
    And no output file should be created

  Scenario: Clean up temporary files
    Given I have a video file "test_video.mp4"
    When I successfully process the video
    Then temporary audio files should be cleaned up
    And only the final SRT file should remain
    And no temporary files should be left in /tmp
