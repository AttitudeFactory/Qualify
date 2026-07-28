# Data Security Evidence Examples

These Data Security Evidence examples are intended to provide helpful information and assist you in completing Meta’s Data Protection Assessment. For any given question, please note there may be more than one way to demonstrate that you meet our requirements. Only a member of Meta’s review team can make a final determination on whether the evidence provided meets the requirements of our Data Protection Assessment. In addition to using this guide, we recommend consulting with your Chief Information Officer, the person with an equivalent role within your organization, or a qualified cybersecurity firm when preparing your responses to the Meta’s Data Protection Assessment to ensure your responses are complete and accurate.

## Preparing to Answer Data Security Questions

### **Data Flows**

Create a data flow diagram or description that shows how your app or system processes Platform Data.

1. **Client side:** Include all client software, such as browsers, mobile devices, and other supported device types.
2. **Server side:**
   * Identify components where Platform Data enters or exits the server environment (e.g., web listeners and REST APIs).
   * Identify components where Platform Data is written to persistent or durable storage (e.g., databases, disks, or log files).
   * Specify the hosting model (e.g., self-hosted, IaaS, PaaS, BaaS, or hybrid).

To meet our requirements, the data flow diagram or description should include:

1. Where Meta API access tokens are generated, transmitted, stored, and renewed (if applicable).
2. How you fetch Platform Data from Meta's APIs, including PII like name, email address, gender, birthdate, and other user data.
3. How you use, store, and transmit this data.
4. Any 4th parties to which Platform Data is sent.

## Preparing Evidence

When submitting evidence to support your data security measures, please refer to the Evidence Guide provided in this document for examples of acceptable evidence. We accept common document file types, screenshots, and screen recordings. Ensure that files are not password protected and do not exceed 2 GB each. Accepted file types include .xls, .xlsx, .csv, .doc, .docx, .pdf, .txt, .jpeg, .jpg, .png, .ppt, .pptx, .mov, .mp4, .zip, and .zipx.

**Redacting Sensitive Data**

Before submission, remove any sensitive data from your evidence. This includes, but is not limited to:

* Health and financial data
* IP addresses, passwords, credentials, and access tokens
* Encryption keys and physical addresses
* Personally Identifying Information (PII) such as names, email addresses, user IDs, birthdates, and location data
* Any data potentially identifying individuals indirectly, such as cultural, social, or political identities
* Details of vulnerabilities, especially those involving children under the age of 13

**Types of Evidence Required**

Meta requires two types of documentation for each data security question:

1. **[Policy or Procedure Evidence](https://developers.facebook.com/docs/resp-plat-initiatives/data-protection-assessment/data-security/version2.5#policy-procedure-evidence)**: This should be a document detailing your data security policies or procedures that align with Meta's standards. It can be an excerpt from internal policies, part of an internal wiki, or a newly created document.
2. **[Implementation Evidence](https://developers.facebook.com/docs/resp-plat-initiatives/data-protection-assessment/data-security/version2.5#implementation-evidence)**: This should demonstrate the practical application of your policies or procedures, such as tool configurations or screenshots showing the implemented measures.

**Guidelines for Evidence Submission**

* **Policy or Procedure Evidence**: Must clearly articulate how your measures meet or exceed Meta's requirements. Only include relevant sections necessary for the review.
* **Implementation Evidence**: Provide screenshots or screen recordings that accurately represent how you have applied the security measures. Ensure the evidence is as detailed as the examples provided by Meta.

## Q3.1-9 Evidence Examples - Protecting Meta Platform Data at Rest in a Server or Backend Environment

### Q3.1-9.b.i Example

A developer has created and regularly updates a Data Security Policy, which describes how the organization securely processes and protects data of varying levels of sensitivity.

A policy of this type might contain the following sections:

* Title Page and date
* Revision History
* Purpose
* Scope & Applicability
* Table of contents
  + Encryption Standard
    - Encryption algorithms
    - Encryption at rest
    - Encryption in transit
  + Data Classification and Data Handling
    - Backend / Cloud Services
    - Personal and Organizational Endpoint Devices
  + Data Storage Architecture
    - Backend
    - Personal and Organizational Endpoint Devices
  + Data Protection Risks
  + Responsibilities
    - Data Access & Use

### Q3.1-9.b.ii Examples

[AWS RDS](https://l.facebook.com/l.php?u=https%3A%2F%2Faws.amazon.com%2Frds%2F&h=AUCZ0EPp9e3baeCi1AU7lcXW0n78JJrSNyk-9OcH4aRrepX4VRPcCzuo-H2HRPhCLnsUmew-pcaqee1QWEaT2_2LglN67oSUBTRcSKnj4VCzBmUPKyn08qYgxRrh3o9clgryUSi23IMnqfrH) - encryption at rest is configurable in AWS RDS, so developers must make sure that the configuration option is set to apply this protection.

For a representative RDS instance that contains Platform Data, use the AWS CLI tool to fetch its StorageEncrypted configuration.

```
# List RDS instances in default region
$ aws rds describe-db-instances \
  --query 'DBInstances[*].DBInstanceIdentifier'

[
    "database-1",
    "database-2"
]

# For each instance returned, retrieve the storage encrypted config
$ aws rds describe-db-instances \
  --db-instance-identifier database-1 \
  --query 'DBInstances[*].StorageEncrypted'
[
    true
]

$ aws rds describe-db-instances \
  --db-instance-identifier database-2 \
  --query 'DBInstances[*].StorageEncrypted'
[
    true
]
```

---

You may also take a screenshot of the AWS console showing that storage encryption is enabled. [Consult AWS documentation on encryption at rest](https://l.facebook.com/l.php?u=https%3A%2F%2Fdocs.aws.amazon.com%2FAmazonRDS%2Flatest%2FUserGuide%2FOverview.Encryption.html&h=AUDMD1lXjw9q868IG1T-XYJLhZse8nC3lF6RGUdMbDjm2qzlEnx6IGiA4NgUlapAGtPz3cQthLqn4HapUvYJ_Ai253j3DSK8Tk1BWRYrEptgZJaGMjIoBVbyRQZJvw5X73bmsnbnpmfLTCFC).

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=1347893889426304&version=1726710699)

---

AWS DynamoDB is encrypted at rest by default. You can fetch the encryption at rest configuration for a table using these commands.

```
$ aws dynamodb list-tables --output table

--------------
| ListTables |
+------------+
||TableNames||
|+----------+|
||  Users   ||
|+----------+|


$ aws dynamodb describe-table \
 --table-name Users \
 --query "Table.SSEDescription.Status"

"ENABLED"
```

---

AWS DocumentDB must be configured to apply encryption at rest. For a representative cluster that contains Platform Data, use these commands to fetch the StorageEncrypted configuration.

```
$ aws docdb describe-db-clusters --query 'DBClusters[*].DBClusterIdentifier'

[
    "docdb-users"
]

$ aws docdb describe-db-clusters \
  --db-cluster-identifier 'docdb-users' \
  --query 'DBClusters[*].StorageEncrypted'
[
    true
]
```

---

AWS S3 buckets may be configured to apply encryption at rest to all objects created within the bucket. Use these commands to list buckets and fetch the configuration for default bucket encryption.

```
$ aws s3api list-buckets --output table --query "Buckets[*].Name"

---------------------------------------------
|                ListBuckets                |
+-------------------------------------------+
|  platform.storage                         |
+-------------------------------------------+

$ aws s3api get-bucket-encryption \
  --bucket  platform.storage \
  --query "ServerSideEncryptionConfiguration.Rules[*].ApplyServerSideEncryptionByDefault" \
  --output table
---------------------
|GetBucketEncryption|
+-------------------+
|   SSEAlgorithm    |
+-------------------+
|  AES256           |
+-------------------+
```

---

**Microsoft Azure**

Consult [Microsoft’s documentation on encryption at rest in Azure](https://l.facebook.com/l.php?u=https%3A%2F%2Fdocs.microsoft.com%2Fen-us%2Fazure%2Fsecurity%2Ffundamentals%2Fencryption-atrest&h=AUAosKUNtHEjr6vEnX-WW6Or-oTJvsuqPD8i0PDHJivxAI7NZXfLJT32-z78dx134xmbimrKg9pg2zmZUVs0cnqL4sFQ0s-G3YBK1JJEf3JnzR5-ZHi7K6c03zxMgF3bPhiL9wR-uOpUuUz1) that’s relevant to the organization’s use of their services.

**Google Cloud Platform**

Consult [Google’s documentation on encryption at rest on Google Cloud Platform.](https://l.facebook.com/l.php?u=https%3A%2F%2Fcloud.google.com%2Fdocs%2Fsecurity%2Fencryption%2Fdefault-encryption&h=AUDIRnbPlGm5FidN9-o_IjLPRewDwoAh85FdtLaVp1x02ooITJkf5CRU3gcbE5HdAPjq30wRzvdfdBAcfJHQGmSDqTtZdGwtenkbbpuPJQjC9c1FMqk_ffhtNRxWSeTJrC7rDI_M5AeptWh2k512t1GlQA2N4Q)

## Q3.1-10 Evidence Examples - Protecting Meta Platform Data at Rest on Organizational and Personal Devices

### Q3.1-10.a.i, Q3.1-10.a.iii Example

A developer has created and regularly updates a Data Security Policy, which describes how the organization securely processes and protects data of varying levels of sensitivity.

[See examples in section Q3.1-9.b.i of this page](https://developers.facebook.com/docs/development/maintaining-data-access/data-protection-assessment/v3.1/data-security-examples/#q3-1-9-b-i-example)

### Q3.1-10.a.ii Examples

Enforcing full disk encryption on managed devices (e.g., Intune/BitLocker on Windows or FileVault on Mac). [https://learn.microsoft.com/en-us/mem/intune/protect/encrypt-devices](https://l.facebook.com/l.php?u=https%3A%2F%2Flearn.microsoft.com%2Fen-us%2Fmem%2Fintune%2Fprotect%2Fencrypt-devices&h=AUAnBOg8mRz1sRYWbX-ZFT2zOusgPW4knTK01cxTGgny1ryv6NI2wcsZ9_kpNHTQyoLIcZEV4Ajvig3ZCSvTBCiaDrBUbduXBMq6T6DnreaiX6Sq1Or7m52ellv8Ml_XUVFv8zE9wcHHMsqo)

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=405466871854607&version=1726710699)

---

M365/O365 Cheat Sheets & Templates

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=1093003335377178&version=1726710699)![](https://lookaside.fbsbx.com/elementpath/media/?media_id=371500635664665&version=1726710699)![](https://lookaside.fbsbx.com/elementpath/media/?media_id=1890085394759830&version=1726710699)

### Q3.1-10.c.i Example

A developer has created and regularly updates an Acceptable Use Policy, which describes how the organization securely processes and handles data of varying levels of sensitivity.

The policy states that people in the organization must not store Meta Platform Data (or PII) on organizational devices (laptops, tablets, etc.) and removable media (USB devices, phones, etc.).

Some developers may have a related data handling or data classification policy that classifies the types of data that this prohibition applies to (e.g., all PII data).

## Q3.1-11 Evidence Examples - Protecting Meta Platform Data in Transit

### Q3.1-11.a.i Example

A developer has created and regularly updates a Data Security Policy, which describes how the organization securely processes and protects data of varying levels of sensitivity, including through the use of encryption in transit.

[See the example in section Q3.1-9.b.i of this page](https://developers.facebook.com/docs/development/maintaining-data-access/data-protection-assessment/v3.1/data-security-examples/#q3-1-9-b-i-example)

### Q3.1-11.a.ii Examples

Qualys SSL Report

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=749130786299921&version=1726710699)![](https://lookaside.fbsbx.com/elementpath/media/?media_id=647596009598476&version=1726710699)

## Q3.1-12 Evidence Examples - Application and Cloud Security Testing

### Q3.1-12.a.i, Q3.1-12.b.i Example

A developer has created and regularly updates a Vulnerability Management Policy, which describes how the organization’s vulnerability identification, testing, and remediation processes.

A policy of this type might contain the following sections:

* Title Page with publication date
* Revision History
* Purpose
* Scope and Applicability
* Table of contents:
  + Roles and Responsibilities
  + Vulnerability Management
    - Identification and Prioritization
    - Vulnerability Testing
    - Frequency of Testing
    - Remediation
  + Patch Management Requirements
    - Patch Identification and Prioritization
    - Patch Testing
    - Patch Application
    - Patch Remediation
  + Enforcement
  + Contacts
  + Associated Documents

### Q3.1-12.a.ii, Q3.1-12.b.ii Examples

SAST Scan from Snyk with findings: [https://snyk.io/blog/sast-and-sca-better-together-with-snyk/](https://l.facebook.com/l.php?u=https%3A%2F%2Fsnyk.io%2Fblog%2Fsast-and-sca-better-together-with-snyk%2F&h=AUCZ727DvaraRO-3fDAker28OuUc9B-XZQB4alFtbuN8wBjjNZhbCrTWCSA285eYol43d3cx7bm9sC9ssgfIE4DxO48uH3JmWGylDozzCrSzX4AYCh7Sjt86CddTgM4VP-KGfpYIulDC2DA6)

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=882409510339742&version=1726710699)

---

Example [SAST Scan from GitLab with findings:](https://l.facebook.com/l.php?u=https%3A%2F%2Fdocs.gitlab.com%2Fee%2Fuser%2Fapplication_security%2Fsast%2F&h=AUCK6mXGyxgG9eet1SrmY_y59OTFQPg5-yZRTWR4Z1Ys9GjJpbsxXDWy-PWSgAMZXHXrhiZUml7AoTG7Ul7ks_0vzsh5aQcsAX2qMolhisQ5XB40iC_OfCzaIMD_NZ3HeIl0FlUEPU_RlTEs)

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=245980108469481&version=1726710699)

---

Example [Acunetix DAST Scan with findings:](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.acunetix.com%2Fvulnerability-assessment-tool%2F&h=AUBbvy7yiFCsYF5ZDX8pTlV2JQgHTtHw11W5H3M3EpUlnnolc-HWUvoCJIzEwV6KL1pJ-tGb2UOeBDDW3WhErW-1E8eQ4VNzu73jPUAjAslTId4GIMq0XtNUx6aTyAOcluDtndLHandbjk5n)

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=918979252822331&version=1726710699)

---

Example Penetration Test report that includes test date and a count of vulnerabilities showing no critical or high severity findings that are unremediated:

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=874238154448090&version=1726710699)![](https://lookaside.fbsbx.com/elementpath/media/?media_id=929186825241732&version=1726710699)

### Q3.1-12.c.i Example

A developer has created and regularly updates a Cloud Security Policy, which describes the organization’s management, security controls/ configurations, and remediation processes regarding their cloud environment.

A policy of this type might contain the following sections:

* Title Page with publication date
* Revision History
* Purpose
* Scope and Applicability
* Table of contents:
  + Roles and Responsibilities
  + Acceptable Use of Cloud Services
  + Security Controls
    - Cloud Configurations
    - Configurations Reviews
      * Frequency of scanning
      * Vulnerability Remediation
  + Enforcement
  + Contacts
  + Associated Documents

### Q3.1-12.c.ii Examples

Cloud Configuration Review - A developer uses NCC Scout Suite using the default ruleset for their cloud provider (in this case, AWS) to review their cloud configuration for vulnerabilities and security issues. The tool outputs a JSON file containing the detailed run results. In this example, there are a number of issues flagged as “Danger” severity that the developer needs to review and resolve.
The raw NCC Scout Suite JSON file contains details about your cloud environment that you should not upload. Instead, filter the responses to show the count of findings by severity.

```
$ python3 scout.py aws --no-browser
2022-08-22 11:39:38 localhost scout[76981] INFO Saving data to scoutsuite-report/scoutsuite-results/scoutsuite_results_aws-043954759379.js

$ cd scoutsuite-report/scoutsuite-results
$ tail -n +2 scoutsuite_results_aws-043954750000.js| jq '. | {last_run}'

{
  "last_run": {
    "ruleset_about": "This ruleset consists of numerous rules that are considered standard by ********. The rules enabled range from violations of well-known security best practices to gaps resulting from less-known security implications of provider-specific mechanisms. Additional rules exist, some of them requiring extra-parameters to be configured, and some of them being applicable to a limited number of users.",
    "ruleset_name": "default",
    "run_parameters": {
      "excluded_regions": [],
      "regions": [],
      "services": [],
      "skipped_services": []
    },
    "summary": {
      "acm": {
        "checked_items": 4,
        "flagged_items": 2,
        "max_level": "warning",
        "resources_count": 2,
        "rules_count": 2
      },
      "awslambda": {
        "checked_items": 0,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 0,
        "rules_count": 0
      },
      "cloudformation": {
        "checked_items": 11,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 11,
        "rules_count": 1
      },
     ... some sections omitted for brevity ...
    },
    "time": "2022-08-22 11:42:25-0400",
    "version": "5.11.0"
  }
}
```

---

Another approach for conducting a cloud configuration review for developers using Amazon Web Services ruleset.

```
# Show that AWS Foundational Security Best Practices are enabled
$ aws securityhub get-enabled-standards
{
    "StandardsSubscriptions": [
        {
            "StandardsSubscriptionArn": "arn:aws:securityhub:us-west-1:043954759379:subscription/aws-foundational-security-best-practices/v/1.0.0",
            "StandardsArn": "arn:aws:securityhub:us-west-1::standards/aws-foundational-security-best-practices/v/1.0.0",
            "StandardsStatus": "READY"
        }
    ]
}

# Show that aggregator is configured for a representative region used to process Platform Data
$ aws securityhub list-finding-aggregators

$ aws securityhub get-finding-aggregator --finding-aggregator-arn '{REPLACE-WITH-FINDING-AGGREGATOR-ARN}'


# Demonstrate that the ruleset is running by fetching active findings and counting the number of lines of output
$ aws securityhub get-findings --query 'Findings[?RecordState==`ACTIVE`]' --filters '{"GeneratorId":[{"Value": "aws-foundational-security","Comparison":"PREFIX"}]}' --output text | wc -l

4876
# Demonstrate that there are no active critical severity findings
$ aws securityhub get-findings --query 'Findings[?Severity.Label==`CRITICAL`] | [?RecordState==`ACTIVE`] | [*][Title, GeneratorId]' --filters '{"GeneratorId":[{"Value": "aws-foundational-security","Comparison":"PREFIX"}]}'
[]
```

---

[AWS Security Hub Findings:](https://l.facebook.com/l.php?u=https%3A%2F%2Faws.amazon.com%2Fsecurity-hub%2F&h=AUCdw3grLNbUc91y3i82Sz3yx8ZTgG5Nsg_W3Pd_3UtQ-aTd4yLySPrbyhC9eAcEmFb2m2TfiigpD7KS7FFA7LP6paopMQ7S0d3_UJj5IAi-wDXsWxQfOUkxBPEAiI5XlHuBwCcK0GFQshKp)

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=1098430414828910&version=1726710699)

## Q3.1-13: Protect the App Secret and Meta Access Tokens

### Q3.1-13.c.i, Q3.1-13.d.i Example

A developer has created a Cryptography Protection Standard that includes procedures on proper handling and protection of secrets or PII.

A policy of this type might contain the following sections:

* Title Page and date
* Revision History
* Purpose
* Scope and Applicability
* Table of Contents
  + Roles and responsibilities
  + App Secret Management
    - Generation and Rotation
    - Storage and Encryption
    - Access Controls
    - Monitoring and Auditing
  + Access Token management
    - Token Lifecycle
    - Authorization and validation
    - Transmission Security
  + Encryption Keys, Vault, and KMS Management
    - Key Generation and Rotation
    - Secure Storage and Distribution
    - Access Controls and Permissions
    - Integration with Key Management Services
    - Secure Vault Implementation
    - Backup and Recovery Procedures

### Q3.1-13.c.ii, Q3.1-13.d.ii Examples

An organization uses AWS Secrets Manager to security store sensitive data, including the Meta App Secret.

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=377032625064273&version=1726710699)

---

An organization has configured its Meta app to require App Secret proof for API calls.

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=1383269612305059&version=1726710699)

---

Examples of deploying application / column level encryption with common hosting providers:

* [AWS CloudFront](https://l.facebook.com/l.php?u=https%3A%2F%2Fdocs.aws.amazon.com%2FAmazonCloudFront%2Flatest%2FDeveloperGuide%2Ffield-level-encryption.html&h=AUCwkeQQbFHcASyt9wW41XZv9D21FiZzqk_0aKhjz79uV1B-UrYnSss40EQhdpthEyoXh_6Da-xySyrYIIsk5VPARe6x89kSXzqhZxfXzrGNSgklaQsJ0746f09zTl-f5IqEahg3rScC37-D)
* [Big Query](https://l.facebook.com/l.php?u=https%3A%2F%2Fcloud.google.com%2Fbigquery%2Fdocs%2Fcolumn-key-encrypt&h=AUASv3sHDN5rYH4anCtuKbEKPynu1ljW22xtbbc9_31gVSqGCfdl537-l_3pby3jt9PI68Dfzyrq6FFJB13q-VDU5xhlu3yqxIAxNZQKr6GYGP1FUSHexJuPeweQo0QapEZEx3dqKm6VkoE5)

## Q3.1-15 Evidence Examples - Protecting Accounts from Unauthorized Access

### Q3.1-15.e.i Examples

A developer has created an Identity and Access Management policy that describes the way the organization handles the access management lifecycle and applies authentication protections like MFA.

A policy of this type might contain the following sections:

* Title Page with publication date
* Revision History
* Purpose
* Table of contents
* Scope
  + Company owned devices
  + Bring Your Own Device (BYOD)
* Definition
* Implementation
  + Management
  + Monitoring
  + Updating
  + Remote Wipe/Poison Pill
* Access Lifecycle Management
  + Access Provisioning Lifecycle
    - Access Review
    - Access Modification
    - Access Revocation
  + User Authentication & Authorization
    - Use of Multi Factor Authentication
    - Enforcement
  + Standard Exceptions

### Q3.1-15.e.ii Examples

AzureAD

An organization uses AzureAD as their Single Sign On solution. This policy requires Multi-Factor Authentication.

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=278257608407342&version=1726710699)

The policy is then mapped to the cloud apps to which it applies. Using this approach, evidence should show the entire Selected items section to make it clear which cloud apps require MFA.

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=7105034746284465&version=1726710699)

---

Okta

This rule requires MFA for all logins.

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=410729498090588&version=1726710699)

---

AWS IAM

This is an example of an AWS IAM policy that allows MFA configuration but forbids other actions if MFA is not present.

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=1103251880863425&version=1726710699)

---

GitHub

An organization has configured GitHub authentication to require MFA for everyone in the organization.

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=842895607872686&version=1726710699)

## Q3.1-16 Evidence Examples - Access Controls

### Q3.1-16.a.i Example

A developer has created an Identity and Access Management policy that describes the way the organization handles the access management lifecycle and applies authentication protections like MFA.

[See examples in section Q3.1-15.e.i of this page](https://developers.facebook.com/docs/development/maintaining-data-access/data-protection-assessment/v3.1/data-security-examples/#315)

### Q3.1-16.a.ii Examples

**Access Is Revoked for Departed Personnel:**

A developer uses Workday as the authoritative source for Human Resources (HR) data, including current employment status. This developer uses Google Cloud Identity as their Identity Provider (IdP) for managing user accounts and granting access to information systems and tools.

A developer submits evidence that access is revoked for departed personnel by submitting a report that shows that a recent (i.e., within the past 12 months) reconciliation report has been run showing that no active user accounts exist in Google Cloud Identity for people who are not active employees according to a Workday report of current employees.

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=355036007413262&version=1726710699)

---

**Access is Revoked When No Longer Used:**

A developer uses Google Cloud Identity as their Identity Provider (IdP) for managing user accounts and granting access to information systems and tools.

A developer submits evidence that access is revoked when it is no longer used (e.g., no logins in the past 6 months) by submitting evidence of their user directory sorted by last sign in to demonstrate that there are no active user accounts where the last sign in was older than this.

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=422291093489556&version=1726710699)

---

**GitHub (Code Repository):**

A developer uses a Single Sign On (SSO) tool for identity management and granting access to information systems and tools. The developer has configured GitHub to require SSO authentication.

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=1220315785424889&version=1726710699)

## Q3.1-17 Evidence Examples - Keep Software Up to Date

### Q3.1-17.a.i, Q3.1-17.b.i, Q3.1-17.c.i Example

A developer has created a Patch Management Policy that describes how the organization will identify, prioritize, test, and deploy patches in their various environments (e.g., mobile, backend, organizational device endpoints).

[See example in section Q3.1-12.b.i of this page](https://developers.facebook.com/docs/development/maintaining-data-access/data-protection-assessment/v3.1/data-security-examples/#q3-1-12-a-i--q3-1-12-b-i-example)

### Q3.1-17.a.ii Examples

Snyk for a NodeJS app

A developer uses the [Synk](https://l.facebook.com/l.php?u=https%3A%2F%2Fsnyk.io%2F%3Ffbclid%3DIwAR1PBsQAJjNS3WrBJN16a_BdkyhezmQaFIYJrZfQ40lUKlSsyJUqbukrdFU&h=AUCBUydazE2Mn2MgQ3MdNIgdjjJkh3NG4QYMCs-OCelHsPtBTcW9XyMz-d_X7U6BX_vbVBlhUgnbxh65fC-9xCEAewOO-ulxqgIRNjru0dBsCCgkQ-Ji23HX8o-GdjhwGAp6oebiEX7gCYxULnhTg_Ae7shF2A) Command Line Interface (CLI) to identify packaged third-party dependencies that have known security vulnerabilities and prioritize based on the severity of those vulnerabilities.

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=1201435570820086&version=1726710699)

---

Snyk Dashboard

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=1075063800491832&version=1726710699)

---

Trivy

A developer uses [Trivy to find vulnerabilities in a machine image.](https://l.facebook.com/l.php?u=https%3A%2F%2Faquasecurity.github.io%2Ftrivy%2Fv0.27.1%2F%3Ffbclid%3DIwAR1cgZiFyLImh1gCGC5XXs8GbjTdwRL8nXSSL9x199Zk1K5VhAkwfWCLRuw&h=AUB_LQbDO8RiZmaVCSjEy5L3EX2kqzKBbH7XfIYD28BFJn7_NxH9SHUNSaZz_Q2lHnRveAex69mKb3Z_nEIYnA2M0W4kvPQ06P4iqhNvH8VgX--z6xdyOyuuKG4a6VSI_4hxRcT5t0PfIfPx) The example image below shows high severity vulnerabilities in libraries included in this image that need to be patched.

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=904495498011021&version=1726710699)

---

NPM Audit

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=2613188745517668&version=1726710699)

---

AWS inspector

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=281824218038157&version=1779124787)

---

Github Security Alerts Enabled

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=6935239529920786&version=1726710699)

---

Puppet

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=909823127251978&version=1726710699)

---

Chef

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=765430181677480&version=1726710699)

---

Ansible

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=349669344640610&version=1726710699)

### Q3.1-17.b.ii Examples

Snyk (Dependency/Components/Library files) scan

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=1913176432434918&version=1726710699)

---

Black Duck by Synopsys

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=403686592147098&version=1726710699)

---

Sonatype Nexus Lifecycle

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=273964742379219&version=1726710699)

---

Mend

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=1035402567535514&version=1726710699)

---

Veracode

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=916593766742878&version=1726710699)

---

OWASP’s Dependency-Check

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=442560264770192&version=1726710699)

---

OWASP Dependency-Track

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=900401121547868&version=1726710699)

---

GitLab Dependency Scanning

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=635994648619863&version=1726710699)

---

JFrog Xray

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=310609058212492&version=1726710699)

### Q3.1-17.c.ii Examples

WSUS (Windows Server Update Services)

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=1041584050252495&version=1726710699)

---

Browsers, operating systems, and other applications used by employees / contributors:
SCCM (System Center Configuration Manager)

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=912281830451378&version=1726710699)![](https://lookaside.fbsbx.com/elementpath/media/?media_id=912650557268998&version=1726710699)

## Q3.1-22 Evidence Examples - Administrator and Application Logging in Backend Environment

### 3.1-22.a, 3.1-22.b.ii, 3.1-22.e.ii, 3.1-22.f.ii, 3.1-22.g.i Example

A developer has created a Logging and Monitoring Policy that includes procedures for collecting, correlating, maintaining, and taking appropriate action on auditable events.

A policy of this type might contain the following sections:

* Title Page with publication date
* Table of contents:
  + Purpose
  + Scope & Applicability
  + Roles & Responsibilities
* Auditable events (Examples below)
  + Authentication attempts
  + Authenticated individual
  + Access time
  + Source of access
  + Duration of access
  + Actions executed
* Auditable content
  + What happened (event ID)
  + When (time stamp)
  + Where (Location, Destination, source IP)
  + Who (user, machine or other unique identifying attributes)
  + What data elements were involved
  + Outcome (Success or failure)
* Audit log location, correlation & protection
  + Where stored or exported to (log files, SIEM tools)
  + Who has access
* Response processes
* Review, Analysis & Reporting
* Audit record retention
  + How long are logs kept
    - Locally
    - Any off site or log server

### 3.1-22.a.i Example

Local Windows Event viewer

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=1072689723813521&version=1726710699)

### 3.1-22.b.iii Example

Windows Security Event auditing example

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=411013514629524&version=1726710699)

### 3.1-22.e.iii Examples

SolarWinds Event correlation workflow example

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=390118583620074&version=1726710699)

---

Windows Powershell

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=581692537504979&version=1726710699)
