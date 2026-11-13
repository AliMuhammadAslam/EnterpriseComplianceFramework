# CSA CCM — Cloud Security Alliance Cloud Controls Matrix

## Overview
The Cloud Security Alliance (CSA) Cloud Controls Matrix (CCM) v4.1 is a cybersecurity control framework for cloud computing environments. It maps to major international standards (ISO 27001, NIST, PCI DSS, GDPR, SOC 2) and provides 207 control objectives across 17 domains (v4.0 had 197). For fintech companies using cloud infrastructure (AWS, Azure, GCP) or offering SaaS products, the CCM provides a structured approach to cloud-specific security and compliance.

## Scope
Applicable to cloud service providers (IaaS, PaaS, SaaS) and cloud service customers. Covers shared responsibility across cloud deployment models (public, private, hybrid) and service models. Freely available from the Cloud Security Alliance.

## 17 Control Domains

### A&A — Audit and Assurance
- **A&A-01**: Audit and Assurance Policy and Procedures
- **A&A-02**: Independent Assessments
- **A&A-03**: Risk Based Planning Assessment
- **A&A-04**: Requirements Compliance
- **A&A-05**: Audit Management Process
- **A&A-06**: Remediation

### AIS — Application and Interface Security
- **AIS-01**: Application and Interface Security Policy and Procedures
- **AIS-02**: Application Security Baseline Requirements
- **AIS-03**: Application Security Metrics
- **AIS-04**: Secure Application Development Lifecycle
- **AIS-05**: Application Security Testing
- **AIS-06**: Secure Application Deployment
- **AIS-07**: Application Vulnerability Remediation
- **AIS-08**: API Security

### BCR — Business Continuity Management and Operational Resilience
- **BCR-01**: Business Continuity Management Policy and Procedures
- **BCR-02**: Risk Assessment and Impact Analysis
- **BCR-03**: Business Continuity Strategy
- **BCR-04**: Business Continuity Planning
- **BCR-05**: Documentation
- **BCR-06**: Business Continuity Exercises
- **BCR-07**: Communication
- **BCR-08**: Backup
- **BCR-09**: Disaster Response Plan
- **BCR-10**: Response Plan Exercise
- **BCR-11**: Equipment Redundancy

### CCC — Change Control and Configuration Management
- **CCC-01**: Change Management Policy and Procedures
- **CCC-02**: Quality Testing
- **CCC-03**: Change Management Technology
- **CCC-04**: Unauthorized Change Protection
- **CCC-05**: Change Agreements
- **CCC-06**: Change Management Baseline
- **CCC-07**: Detection of Baseline Deviation
- **CCC-08**: Exception Management
- **CCC-09**: Change Restoration

### CEK — Cryptography, Encryption, and Key Management
- **CEK-01**: Encryption and Key Management Policy and Procedures
- **CEK-02**: CEK Roles and Responsibilities
- **CEK-03**: Data Protection
- **CEK-04**: Encryption Algorithm
- **CEK-05**: Encryption Change Management
- **CEK-06**: Encryption Change Cost Benefit Analysis
- **CEK-07**: Encryption Risk Management
- **CEK-08**: Service Customer Key Management Capability
- **CEK-09**: Encryption and Key Management Audit
- **CEK-10**: Key Generation
- **CEK-11**: Key Purpose
- **CEK-12**: Key Rotation
- **CEK-13**: Key Revocation
- **CEK-14**: Key Destruction
- **CEK-15**: Key Activation
- **CEK-16**: Key Suspension
- **CEK-17**: Key Deactivation
- **CEK-18**: Key Archival
- **CEK-19**: Key Compromise
- **CEK-20**: Key Recovery
- **CEK-21**: Key Inventory Management

### DCS — Datacenter Security
- **DCS-01**: Physical and Environmental Security Policy and Procedures
- **DCS-02**: Off-Site Equipment Disposal Policy and Procedures
- **DCS-03**: Off-Site Transfer Authorization Policy and Procedures
- **DCS-04**: Secure Area Policy and Procedures
- **DCS-05**: Secure Media Transportation Policy and Procedures
- **DCS-06**: Assets Classification
- **DCS-07**: Assets Cataloguing and Tracking
- **DCS-08**: Controlled Physical Access Points
- **DCS-09**: Equipment Identification
- **DCS-10**: Secure Area Authorization
- **DCS-11**: Surveillance System
- **DCS-12**: Adverse Event Response Training
- **DCS-13**: Cabling Security
- **DCS-14**: Environmental Systems
- **DCS-15**: Secure Utilities
- **DCS-16**: Equipment Location
- **DCS-17**: Datacenter Metrics
- **DCS-18**: Datacenter Operations Resilience

### DSP — Data Security and Privacy Lifecycle Management
- **DSP-01**: Security and Privacy Policy and Procedures
- **DSP-02**: Secure Disposal
- **DSP-03**: Data Inventory
- **DSP-04**: Data Classification
- **DSP-05**: Data Flow Documentation
- **DSP-06**: Data Ownership and Stewardship
- **DSP-07**: Data Protection by Design and Default
- **DSP-08**: Data Privacy by Design and Default
- **DSP-09**: Data Protection Impact Assessment
- **DSP-10**: Sensitive Data Transfer
- **DSP-11**: Personal Data Access, Reversal, Rectification and Deletion
- **DSP-12**: Limitation of Purpose in Personal Data Processing
- **DSP-13**: Personal Data Sub-processing
- **DSP-14**: Disclosure of Data Sub-processors
- **DSP-15**: Limitation of Production Data Use
- **DSP-16**: Data Retention and Deletion
- **DSP-17**: Sensitive Data Protection
- **DSP-18**: Disclosure Notification
- **DSP-19**: Data Location

### GRC — Governance, Risk, and Compliance
- **GRC-01**: Governance Program Policy and Procedures
- **GRC-02**: Risk Management Program
- **GRC-03**: Organizational Policy Reviews
- **GRC-04**: Policy Exception Process
- **GRC-05**: Information Security Program
- **GRC-06**: Governance Responsibility Model
- **GRC-07**: Information System Regulatory Mapping
- **GRC-08**: Special Interest Groups

### HRS — Human Resources
- **HRS-01**: Background Screening Policy and Procedures
- **HRS-02**: Acceptable Use of Technology Policy and Procedures
- **HRS-03**: Clean Desk Policy and Procedures
- **HRS-04**: Remote and Home Working Policy and Procedures
- **HRS-05**: Asset returns
- **HRS-06**: Employment Termination
- **HRS-07**: Employment Agreement Process
- **HRS-08**: Employment Agreement Content
- **HRS-09**: Personnel Roles and Responsibilities
- **HRS-10**: Non-Disclosure Agreements
- **HRS-11**: Security Awareness Training
- **HRS-12**: Personal and Sensitive Data Awareness and Training
- **HRS-13**: Compliance User Responsibility

### IAM — Identity and Access Management
- **IAM-01**: Identity and Access Management Policy and Procedures
- **IAM-02**: Credentials Management Policy and Procedures
- **IAM-03**: Identity Inventory
- **IAM-04**: Separation of Duties
- **IAM-05**: Least Privilege
- **IAM-06**: Access Provisioning
- **IAM-07**: Access Changes and Revocation
- **IAM-08**: Access Review
- **IAM-09**: Segregation of Privileged Access Roles
- **IAM-10**: Management of Privileged Access Roles
- **IAM-11**: Service Customers Approval for Agreed Privileged Access Roles
- **IAM-12**: Unique Identities
- **IAM-13**: Strong Authentication
- **IAM-14**: Credentials Management
- **IAM-15**: Authorization Mechanisms

### IPY — Interoperability and Portability
- **IPY-01**: Interoperability and Portability Policy and Procedures
- **IPY-02**: Application Interface Availability
- **IPY-03**: Secure Interoperability and Portability Management
- **IPY-04**: Data Portability Contractual Obligations

### I&S — Infrastructure Security (IVS, Infrastructure and Virtualization Security, in v4.0)
- **I&S-01**: Infrastructure and Virtualization Security Policy and Procedures
- **I&S-02**: Capacity and Resource Planning
- **I&S-03**: Network Security
- **I&S-04**: OS Hardening and Base Controls
- **I&S-05**: Production and Non-Production Environments
- **I&S-06**: Segmentation and Segregation
- **I&S-07**: Migration to Cloud Environments
- **I&S-08**: Network Architecture Documentation
- **I&S-09**: Network Defense

### LOG — Logging and Monitoring
- **LOG-01**: Logging and Monitoring Policy and Procedures
- **LOG-02**: Audit Logs Protection
- **LOG-03**: Security Monitoring and Alerting
- **LOG-04**: Audit Logs Access and Accountability
- **LOG-05**: Audit Logs Monitoring and Response
- **LOG-06**: Clock Synchronization
- **LOG-07**: Logging Scope
- **LOG-08**: Audit Logs Sanitization
- **LOG-09**: Log Records
- **LOG-10**: Audit Records Protection
- **LOG-11**: Encryption Monitoring and Reporting
- **LOG-12**: Transaction/Activity Logging
- **LOG-13**: Access Control Logs
- **LOG-14**: Failures and Anomalies Reporting

### SEF — Security Incident Management, E-Discovery, & Cloud Forensics
- **SEF-01**: Security Incident Management Policy and Procedures
- **SEF-02**: Service Management Policy and Procedures
- **SEF-03**: Incident Response Plans
- **SEF-04**: Incident Response Testing
- **SEF-05**: Incident Response Metrics
- **SEF-06**: Event Triage Processes
- **SEF-07**: Incident Management and Response
- **SEF-08**: Security Breach Notification
- **SEF-09**: Incident Records Management
- **SEF-10**: Points of Contact Maintenance

### STA — Supply Chain Management, Transparency, and Accountability
- **STA-01**: Supply Chain Risk Management Policies and Procedures
- **STA-02**: SSRM Policy and Procedures
- **STA-03**: SSRM Supply Chain
- **STA-04**: SSRM Guidance
- **STA-05**: SSRM Control Ownership
- **STA-06**: SSRM Documentation Review
- **STA-07**: SSRM Control Implementation
- **STA-08**: Supply Chain Inventory
- **STA-09**: Service Bill of Material (BOM)
- **STA-10**: Supply Chain Risk Management
- **STA-11**: Primary Service and Contractual Agreement
- **STA-12**: Supply Chain Agreement Review
- **STA-13**: Supply Chain Compliance Assessment
- **STA-14**: Supply Chain Service Agreement Compliance
- **STA-15**: Supply Chain Governance Review
- **STA-16**: Supply Chain Data Security Assessment

### TVM — Threat and Vulnerability Management
- **TVM-01**: Threat and Vulnerability Management Policy and Procedures
- **TVM-02**: Malware and Malicious Instructions Protection Policy and Procedures
- **TVM-03**: Vulnerability Identification
- **TVM-04**: Threat Analysis and Modelling
- **TVM-05**: Detection Updates
- **TVM-06**: External Library Vulnerabilities
- **TVM-07**: Penetration Testing
- **TVM-08**: Vulnerability Remediation Schedule
- **TVM-09**: Vulnerability Prioritization
- **TVM-10**: Threat Response
- **TVM-11**: Vulnerability Management Reporting
- **TVM-12**: Vulnerability Management Metrics

### UEM — Universal Endpoint Management
- **UEM-01**: Endpoint Devices Policy and Procedures
- **UEM-02**: Application and Service Approval
- **UEM-03**: Compatibility
- **UEM-04**: Endpoint Inventory
- **UEM-05**: Endpoint Management
- **UEM-06**: Automatic Lock Screen
- **UEM-07**: Operating Systems
- **UEM-08**: Storage Encryption
- **UEM-09**: Anti-Malware Detection and Prevention
- **UEM-10**: Software Firewall
- **UEM-11**: Data Loss Prevention
- **UEM-12**: Remote Locate
- **UEM-13**: Remote Wipe
- **UEM-14**: Third-Party Endpoint Security Posture


## Relevance to Fintech
- Cloud security baseline for fintech SaaS platforms
- Compliance mapping: CCM maps to ISO 27001, SOC 2, PCI DSS, GDPR
- Shared responsibility understanding between fintech and cloud provider
- API security controls for payment APIs and open banking interfaces
- SBP's Framework on Outsourcing to Cloud Service Providers (2023) also applies to SBP-regulated entities; SBP approval is needed only for offshore cloud outsourcing of material workloads by banks, MFBs, DBs, DFIs and designated PSOs/PSPs
