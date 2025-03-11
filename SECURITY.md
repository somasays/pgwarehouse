# Security Enhancements for PGWarehouse

This document outlines the security improvements made to the PGWarehouse codebase to address potential vulnerabilities.

## Security Fixes

### 1. SQL Injection Prevention
- Added parameterized queries throughout the codebase to prevent SQL injection
- Implemented input validation for table and column names
- Properly quoted database identifiers

### 2. Command Injection Prevention
- Replaced `shell=True` with argument arrays in subprocess calls
- Implemented proper command argument escaping
- Added input validation for command arguments

### 3. Credential Handling
- Prevented exposure of credentials in environment variables
- Implemented secure credential passing to database connections
- Added filtering of sensitive information in logs

### 4. File System Security
- Added path validation for all file operations
- Implemented secure file permissions (0o600) for sensitive data files
- Added safeguards against directory traversal attacks

### 5. Error Handling
- Improved error handling to prevent leakage of sensitive information
- Removed stack traces from user-facing error messages
- Implemented proper exception handling

### 6. Input Validation
- Added regex validation for critical inputs such as table names
- Implemented type checking for function parameters
- Added boundary checks for numeric inputs

## Best Practices for Configuration

1. Use environment variables for credentials instead of config files when possible
2. Implement a secrets manager or vault for production deployments
3. Run PGWarehouse with minimal privileges required for operation
4. Regularly rotate database credentials
5. Enable SSL/TLS for all database connections

## Reporting Security Issues

Please report security vulnerabilities to the project maintainer at https://github.com/scottpersinger/.