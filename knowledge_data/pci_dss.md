# PCI DSS — Payment Card Industry Data Security Standard

## Overview
PCI DSS is a set of security standards established by the Payment Card Industry Security Standards Council (PCI SSC), founded by major credit card brands (Visa, Mastercard, American Express, Discover, JCB). It is designed to ensure that all companies that accept, process, store, or transmit credit card information maintain a secure environment. The current version is PCI DSS v4.0 (released March 2022, mandatory from March 2025).

## Scope
Applies to all entities that store, process, or transmit cardholder data (CHD) or sensitive authentication data (SAD). This includes merchants, processors, acquirers, issuers, and service providers. Scope includes all system components that are included in or connected to the cardholder data environment (CDE).

## 12 Requirements (Organized by 6 Goals)

### Goal 1: Build and Maintain a Secure Network and Systems
**Requirement 1**: Install and maintain network security controls (firewalls, network segmentation)
**Requirement 2**: Apply secure configurations to all system components (remove vendor defaults, harden systems)

### Goal 2: Protect Account Data
**Requirement 3**: Protect stored account data (encryption, masking, truncation, hashing)
**Requirement 4**: Protect cardholder data with strong cryptography during transmission over open, public networks

### Goal 3: Maintain a Vulnerability Management Program
**Requirement 5**: Protect all systems and networks from malicious software (anti-malware solutions)
**Requirement 6**: Develop and maintain secure systems and software (patch management, secure SDLC)

### Goal 4: Implement Strong Access Control Measures
**Requirement 7**: Restrict access to system components and cardholder data by business need-to-know
**Requirement 8**: Identify users and authenticate access to system components (MFA, password policies)
**Requirement 9**: Restrict physical access to cardholder data (facility access controls, visitor management)

### Goal 5: Regularly Monitor and Test Networks
**Requirement 10**: Log and monitor all access to system components and cardholder data (audit trails, SIEM)
**Requirement 11**: Test security of systems and networks regularly (vulnerability scans, penetration testing)

### Goal 6: Maintain an Information Security Policy
**Requirement 12**: Support information security with organizational policies and programs (security policy, risk assessment, awareness training, incident response)

## PCI DSS v4.0 Key Changes
- **Customized Approach**: Organizations can implement controls using a customized approach (instead of only defined approach)
- **Targeted Risk Analysis**: Flexibility to define frequency of certain activities based on risk
- **Enhanced Authentication**: Multi-factor authentication (MFA) required for all access into the CDE
- **Expanded Scope**: New requirements for e-commerce and phishing protection
- **Continuous Compliance**: Emphasis on security as a continuous process, not just annual assessment

## Compliance Levels (Merchants)
- **Level 1**: Over 6 million transactions/year — requires annual on-site assessment by QSA
- **Level 2**: 1-6 million transactions/year — annual Self-Assessment Questionnaire (SAQ)
- **Level 3**: 20,000-1 million e-commerce transactions/year — annual SAQ
- **Level 4**: Less than 20,000 e-commerce or up to 1 million other transactions — annual SAQ

## Penalties for Non-Compliance
- Fines from payment card brands: $5,000 to $100,000 per month
- Increased transaction fees
- Loss of ability to process card payments
- Liability for fraudulent charges after a data breach
- Reputational damage and loss of customer trust
- Potential legal action and regulatory penalties
