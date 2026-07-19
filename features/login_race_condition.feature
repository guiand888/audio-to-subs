Feature: Login Race Condition
  As a user starting the container stack
  I want to log in on the first try without waiting for the backend to become ready
  So that I have a smooth and polished experience

  Background:
    Given the application database is initialized
    And the session secret file exists
    And an admin user "admin" with password "test-secure-password-12345" exists

  Scenario: First boot generates the session secret file
    Given the session secret file does not exist
    And no SESSION_SECRET environment variable is set
    And SESSION_SECRET_FILE points to the missing file
    When the application is created
    Then the session secret file should be generated
    And the session secret file should not contain the placeholder value

  Scenario: Login with valid credentials on a ready backend
    When I log in with username "admin" and password "test-secure-password-12345"
    Then the response status should be 200
    And the response should contain a session cookie
    And the response should contain the username "admin"

  Scenario: Login with wrong password returns 401
    When I log in with username "admin" and password "wrongpassword"
    Then the response status should be 401
    And the response should contain "Invalid username or password"

  Scenario: Login with unknown user returns 401
    When I log in with username "ghost" and password "anypassword"
    Then the response status should be 401
    And the response should contain "Invalid username or password"

  Scenario: Access a protected route without a session cookie
    When I request the jobs list without authentication
    Then the response status should be 401

  Scenario: Access a protected route with a valid session cookie
    Given I am logged in as "admin"
    When I request the jobs list with the session cookie
    Then the response status should be 200

  Scenario: Session cookie is validated against the signing secret
    Given I am logged in as "admin"
    But the session secret has been rotated
    When I request the jobs list with the old session cookie
    Then the response status should be 401
    And the session cookie should be cleared

  Scenario: Healthz returns 200 when the database is reachable
    When I check the health endpoint
    Then the response status should be 200
    And the response should contain database status "ok"
