# Security Policy - Evidence-Grade Contacts PoC

This document outlines security practices and policies for the EGC proof-of-concept system.

## Data Handling & Privacy

### Data Minimization
- **Business contacts only**: No personal data beyond professional roles and business contact information
- **Public sources only**: Only extract data that is publicly accessible on company websites
- **No sensitive data**: Avoid personal phone numbers, personal emails, or non-business information

### Source Compliance
- **robots.txt enforcement**: Strict compliance with robots.txt directives
- **Terms of Service**: Respect website ToS; no access to explicitly forbidden sources
- **Rate limiting**: Implement respectful crawling with configured delays and quotas

### Red-flag Sources (NO-GO)
Never access these platforms:
- LinkedIn
- Twitter/X
- Facebook/Meta properties  
- Instagram
- Any platform with explicit anti-scraping ToS

## Secrets Management

### Environment Variables Only
**All secrets must be provided via environment variables:**

```bash
# Required for SMTP probing
export SMTP_PROBE_SENDER={{YOUR_EMAIL}}

# Optional proxy configuration  
export PROXY_URL={{PROXY_URL}}

# Optional database credentials
export DB_URL={{DATABASE_URL}}
```

### Never Hardcode
❌ **Never commit secrets in code:**
```python
# WRONG - hardcoded credentials
smtp_sender = "admin@company.com"
proxy_url = "http://proxy:8080"
```

✅ **Always use environment variables:**
```python
# CORRECT - environment variables
import os
smtp_sender = os.getenv("SMTP_PROBE_SENDER")
proxy_url = os.getenv("PROXY_URL")
```

### Configuration Files
- **Public configs**: `config/example.yaml` - safe to commit
- **Private configs**: `config/production.yaml` - add to .gitignore
- **No secrets in configs**: Use environment variable placeholders

## Data Storage & Retention

### Local Development
- **No persistent storage** of crawled data (PoC limitation)
- **Evidence artifacts**: Screenshots stored temporarily for verification only
- **Automatic cleanup**: Clear output directories between runs

### File System Security
- **Restricted permissions**: Ensure output directories are not world-readable
- **Temporary files**: Clean up all temporary artifacts
- **No backup retention**: Don't create automatic backups of personal data

## Network Security

### HTTPS Only
- All web requests must use HTTPS where available
- Validate SSL certificates  
- No HTTP fallback for sensitive operations

### Proxy Support
- Optional proxy configuration via environment variables
- Proxy credentials via environment variables only
- Log proxy usage for audit purposes

### Rate Limiting & Respect
- **Static requests**: Max 1 RPS per domain
- **Headless requests**: Max 0.2 RPS per domain  
- **Backoff on 403**: Progressive delays (5m → 15m → 60m)
- **Budget limits**: Max 12 seconds per URL

## Access Control

### Development Environment
- **Virtual environment**: Use isolated Python environment (.venv311/)
- **Dependencies**: Pin exact versions in requirements.txt
- **Pre-commit hooks**: Automated security checks before commits

### Production Considerations (Post-PoC)
- Implement proper authentication for API access
- Use secrets management system (AWS Secrets Manager, HashiCorp Vault)
- Implement audit logging for all data access
- Regular security reviews of dependencies

## Data Subject Rights

### Right to Erasure
- **Manual process**: Contact system administrators for deletion requests
- **Business contacts**: Clarify that we process business contact information only
- **Retention**: No long-term retention in PoC (data cleared between runs)

### Contact Information
For data deletion requests or security concerns:
- **Email**: [Insert contact email for security/privacy issues]
- **Response time**: Within 7 business days
- **Process**: Manual review and action required

## Incident Response

### Security Issues
1. **Immediate**: Stop processing and secure the system
2. **Assessment**: Determine scope and impact of the issue  
3. **Notification**: Contact stakeholders within 24 hours
4. **Resolution**: Implement fixes and update security measures
5. **Documentation**: Record incident and lessons learned

### Data Breaches
1. **Contain**: Immediate isolation of affected systems
2. **Assess**: Determine what data may have been compromised
3. **Notify**: Inform affected parties as required by law
4. **Remediate**: Fix vulnerabilities and improve security

## Compliance & Legal

### GDPR/Privacy Laws
- **Lawful basis**: Legitimate interest for business contact processing
- **Data minimization**: Only collect necessary business information
- **Transparency**: Clear documentation of data processing activities
- **Rights**: Provide mechanisms for data subject requests

### Audit Trail
- **Request logging**: Log all HTTP requests with timestamps
- **Error logging**: Record and analyze failure patterns
- **Access logging**: Track who runs the system and when
- **Retention**: Maintain logs for compliance requirements

## Security Testing

### Regular Checks
- **Dependency scanning**: Monitor for known vulnerabilities
- **Code analysis**: Static analysis for security issues
- **Configuration review**: Regular audit of security settings
- **Access review**: Periodic review of who has system access

### Tools Integration
```bash
# Security scanning (example)
safety check                    # Check Python dependencies
bandit -r src/ -r egc/          # Security linting (include CLI)
pip-audit                       # Vulnerability scanning
```

## CLI Security

### Input Validation
- **Path traversal prevention**: All file paths validated and restricted to project directory
- **YAML parsing**: Safe loading only (yaml.safe_load), no arbitrary code execution
- **File permissions**: Automatic validation of read/write permissions before processing
- **Directory creation**: Safe directory creation with proper error handling

### Command Line Arguments
- **No secret injection**: Secrets only via environment variables, never CLI arguments
- **Input sanitization**: File paths validated for existence and accessibility
- **Output isolation**: Output directories created with restricted permissions

## Reporting Security Issues

### Responsible Disclosure
If you discover a security vulnerability:

1. **Do not** create public issues or PRs
2. **Contact** the security team directly at [security email]
3. **Provide** detailed description and steps to reproduce
4. **Allow** reasonable time for response and resolution

### Bug Bounty (Future)
- Not applicable for PoC phase
- Consider implementing for production deployment

## Security Checklist

Before deployment:
- [ ] All secrets moved to environment variables
- [ ] No hardcoded credentials in code
- [ ] .gitignore excludes all sensitive files
- [ ] HTTPS enforced for all external requests
- [ ] Rate limiting configured appropriately  
- [ ] Error messages don't expose sensitive information
- [ ] Dependencies scanned for vulnerabilities
- [ ] Access controls implemented
- [ ] Audit logging enabled
- [ ] Incident response plan documented

---

**Last Updated**: [Current Date]  
**Review Frequency**: Quarterly  
**Owner**: EGC Security Team
