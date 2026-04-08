# SWIFT Customer Security Programme (CSP)

## Overview
The SWIFT Customer Security Programme (CSP) was launched in 2017 in response to high-profile cyber attacks targeting financial institutions connected to the SWIFT network. The CSP establishes mandatory and advisory security controls for all SWIFT users. Compliance is mandatory and attested annually through the KYC Security Attestation (KYC-SA) process. For fintech companies that interface with SWIFT for international payments or correspondent banking, CSP compliance is essential.

## Scope
Applies to all institutions connected to the SWIFT network, including banks, payment service providers, securities firms, and fintechs with SWIFT connectivity. Controls apply to the local SWIFT infrastructure (messaging interface, communication interface, operator PCs) and the broader environment that supports or protects it.

## Customer Security Controls Framework (CSCF) v2024

### Architecture Types
SWIFT categorizes users into architecture types based on their connectivity model:
- **A1**: Users running SWIFT messaging interface (Alliance Lite2, Alliance Access)
- **A2**: Users running SWIFT communication interface (Alliance Connect)
- **A3**: Users connecting through a service bureau or shared infrastructure
- **A4**: Users with standalone Alliance Lite2 Auto client

### Control Categories

#### Mandatory Controls (31 controls — must implement)

##### 1. Restrict Internet Access and Protect Critical Systems
- **1.1**: SWIFT environment protection — secure zone for SWIFT-related components
- **1.2**: Operating system privileged account control
- **1.3**: Virtualization platform protection
- **1.4**: Internet access restriction from SWIFT secure zone

##### 2. Reduce Attack Surface and Vulnerabilities
- **2.1**: Internal data flow security
- **2.2**: Security updates — timely patching of SWIFT and supporting components
- **2.3**: System hardening — secure configuration of all components
- **2.4A**: Back-office data flow security
- **2.6**: Operator session confidentiality and integrity (encryption of operator sessions)
- **2.7**: Vulnerability scanning — regular scans of SWIFT environment
- **2.8A**: Outsourced critical activity protection
- **2.9**: Transaction business controls — verification of business transactions
- **2.10**: Application hardening — secure configuration of SWIFT applications
- **2.11A**: RMA business justification — periodic review of Relationship Management Application authorizations

##### 3. Physically Secure the Environment
- **3.1**: Physical security of SWIFT-related equipment

##### 4. Prevent Compromise of Credentials
- **4.1**: Password policy — complexity, rotation, history
- **4.2**: Multi-factor authentication for SWIFT-related applications and accounts

##### 5. Manage Identities and Segregate Privileges
- **5.1**: Logical access control — need-to-know and least privilege
- **5.2**: Token management — secure handling of SWIFT authentication tokens
- **5.3A**: Personnel vetting process
- **5.4**: Physical and logical password storage

##### 6. Detect Anomalous Activity to Systems or Transaction Records
- **6.1**: Malware protection — anti-malware on all SWIFT components
- **6.2**: Software integrity — verify integrity of SWIFT software
- **6.3**: Database integrity — protect SWIFT database records
- **6.4**: Logging and monitoring — comprehensive logging of SWIFT operations
- **6.5A**: Intrusion detection — network and host-based intrusion detection

##### 7. Plan for Incident Response and Information Sharing
- **7.1**: Cyber incident response planning — documented IRP covering SWIFT environment
- **7.2**: Security training and awareness — annual training for SWIFT operators
- **7.3A**: Penetration testing — regular penetration testing of SWIFT environment
- **7.4A**: Scenario-based risk assessment

#### Advisory Controls (5 controls — recommended best practice)
- Additional controls that enhance security posture beyond mandatory requirements
- Expected to become mandatory in future CSCF versions
- Cover areas such as advanced threat detection and expanded monitoring

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
