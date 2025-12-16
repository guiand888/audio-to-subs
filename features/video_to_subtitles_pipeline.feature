Feature: Video to Subtitle Pipeline
  As a user
  I want to convert video audio to subtitles
  So that I can add captions to my videos

  Background:
    Given FFmpeg is installed and available

  Scenario: Convert single video file to SRT
    Given a video file "sample.mp4" exists
    And a valid Mistral API key is configured
    When I run audio-to-subs with "sample.mp4"
    Then an SRT file "sample.srt" should be created
    And the SRT file should contain timestamped text
    And the timestamps should be properly formatted
    And the temporary audio file should be cleaned up

  Scenario: Handle missing API key
    Given a video file "sample.mp4" exists
    And no API key is configured
    When I run audio-to-subs with "sample.mp4"
    Then I should see an error message about missing API key
    And no SRT file should be created
    And the exit code should be 3

  Scenario: Handle invalid video file
    Given an invalid file "not_a_video.txt" exists
    And a valid Mistral API key is configured
    When I run audio-to-subs with "not_a_video.txt"
    Then I should see an error message about invalid video file
    And no SRT file should be created
    And the exit code should be 1

  Scenario: Handle missing video file
    Given no file "nonexistent.mp4" exists
    And a valid Mistral API key is configured
    When I run audio-to-subs with "nonexistent.mp4"
    Then I should see an error message about file not found
    And no SRT file should be created
    And the exit code should be 1

  Scenario: Batch process multiple videos
    Given video files exist:
      | filename   |
      | video1.mp4 |
      | video2.mp4 |
      | video3.mp4 |
    And a valid Mistral API key is configured
    When I run audio-to-subs with multiple files "video1.mp4 video2.mp4 video3.mp4"
    Then SRT files should be created:
      | filename   |
      | video1.srt |
      | video2.srt |
      | video3.srt |
    And all temporary audio files should be cleaned up

  Scenario: Continue batch processing on single file failure
    Given video files exist:
      | filename   |
      | valid1.mp4 |
      | valid2.mp4 |
    And an invalid file "invalid.txt" exists
    And a valid Mistral API key is configured
    When I run audio-to-subs with multiple files "valid1.mp4 invalid.txt valid2.mp4"
    Then SRT files should be created:
      | filename    |
      | valid1.srt  |
      | valid2.srt  |
    And I should see an error message about "invalid.txt"
    And the exit code should be 1

  Scenario: Use custom output directory
    Given a video file "sample.mp4" exists
    And a valid Mistral API key is configured
    And an output directory "subtitles/" does not exist
    When I run audio-to-subs with "sample.mp4" and output directory "subtitles/"
    Then the output directory "subtitles/" should be created
    And an SRT file "subtitles/sample.srt" should be created

  Scenario: Specify language hint
    Given a video file "french_video.mp4" exists
    And a valid Mistral API key is configured
    When I run audio-to-subs with "french_video.mp4" and language "fr"
    Then an SRT file "french_video.srt" should be created
    And the transcription should use language hint "fr"

  Scenario: Handle FFmpeg not installed
    Given FFmpeg is not available
    And a video file "sample.mp4" exists
    And a valid Mistral API key is configured
    When I run audio-to-subs with "sample.mp4"
    Then I should see an error message about FFmpeg not found
    And no SRT file should be created
    And the exit code should be 2