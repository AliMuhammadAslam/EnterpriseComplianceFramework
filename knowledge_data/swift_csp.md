# SWIFT Customer Security Programme (CSP)

## Overview
The SWIFT Customer Security Programme (CSP) was launched in 2017 in response to high-profile cyber attacks targeting financial institutions connected to the SWIFT network. The CSP establishes mandatory and advisory security controls for all SWIFT users. Compliance is mandatory and attested annually through the KYC Security Attestation (KYC-SA) process. For fintech companies that interface with SWIFT for international payments or correspondent banking, CSP compliance is essential.

## Scope
Applies to all institutions connected to the SWIFT network, including banks, payment service providers, securities firms, and fintechs with SWIFT connectivity. Controls apply to the local SWIFT infrastructure (messaging interface, communication interface, operator PCs) and the broader environment that supports or protects it.

## Customer Security Controls Framework (CSCF) v2027

CSCF v2027 (published 10 July 2026) contains 32 security controls: 26 mandatory and 6 advisory (suffix "A"). Users must attest against it between July 2027 and December 2027. A new CSCF version is generally published each July.

### Architecture Types
- **A1**: Users own the communication interface (and, generally, the messaging interface) licences, which reside within their environment
- **A2**: Users own the messaging interface but not the communication interface; a Swift connectivity provider (for example, a service bureau), a Group Hub or Swift owns the communication interface licence
- **A3**: A Swift connector (for example, Alliance Cloud SIL, Direct Link, Alliance Lite2 AutoClient or Swift Microgateway) is used within the user environment
- **A4**: Customer connector: the user has no Swift footprint but uses a system in its environment (for example, a file transfer solution or middleware server) to connect to a service provider
- **B**: No Swift-specific infrastructure component is used within the user environment

### Controls

##### 1. Restrict Internet Access and Protect Critical Systems
- **1.1**: Swift environment protection
- **1.2**: Operating system privileged account control
- **1.3**: Virtualisation or cloud platform protection
- **1.4**: Restriction of internet access
- **1.5**: Customer environment protection

##### 2. Reduce Attack Surface and Vulnerabilities
- **2.1**: Internal data flow security
- **2.2**: Security updates
- **2.3**: System hardening
- **2.4**: Back-office data flow security
- **2.5A**: External transmission data protection (advisory)
- **2.6**: Operator session confidentiality and integrity
- **2.7**: Vulnerability scanning
- **2.8**: Outsourced critical activity protection
- **2.9**: Transaction business controls
- **2.10**: Application hardening
- **2.11A**: RMA business controls (advisory)

##### 3. Physically Secure the Environment
- **3.1**: Physical security

##### 4. Prevent Compromise of Credentials
- **4.1**: Password policy
- **4.2**: Multi-factor authentication

##### 5. Manage Identities and Segregate Privileges
- **5.1**: Logical access control
- **5.2**: Token management
- **5.3A**: Staff screening process (advisory)
- **5.4**: Password repository protection

##### 6. Detect Anomalous Activity to Systems or Transaction Records
- **6.1**: Malware protection
- **6.2**: Software integrity
- **6.3**: Database integrity
- **6.4**: Logging and monitoring
- **6.5A**: Intrusion detection (advisory)

##### 7. Plan for Incident Response and Information Sharing
- **7.1**: Cyber-incident response planning
- **7.2**: Security training and awareness
- **7.3A**: Penetration testing (advisory)
- **7.4A**: Scenario-based risk assessment (advisory)

### KYC Security Attestation Process

#### Annual Attestation Requirements
- Self-attestation against all mandatory controls
- Attestation submitted via SWIFT's KYC-SA application
- Deadline: December 31 of each year
- Results shared with counterparties via SWIFT's KYC Registry

#### Independent Assessment
- Mandatory independent assessment (internal or external) since 2021
- Assessment must verify compliance with mandatory controls
- Assessment by: internal audit, external auditor, or SWIFT-qualified assessor
- Assessment report retained and available upon request

#### Non-Compliance Consequences
- Non-attested or non-compliant status visible to counterparties
- Counterparties may restrict or terminate SWIFT connectivity
- Regulatory scrutiny: central banks may inquire about SWIFT CSP compliance
- Reputational risk from non-compliant status

## Relevance to Pakistani Fintech
- Banks and financial institutions in Pakistan connected to SWIFT must comply with CSP
- Fintechs providing correspondent banking or cross-border payment services need CSP compliance
- SBP expects SWIFT-connected institutions to meet CSP mandatory controls
- Cross-border remittance services (key fintech vertical in Pakistan) may require SWIFT connectivity
- Service bureaus providing SWIFT access must demonstrate Architecture Type A3 compliance
