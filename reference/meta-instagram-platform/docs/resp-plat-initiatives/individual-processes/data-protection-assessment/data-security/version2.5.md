# Data Security Requirements

The following data security requirements correspond to the 2022-23 Data Protection Assessment.

![](https://static.xx.fbcdn.net/rsrc.php/v4/y4/r/-PAXP-deijE.gif)

Something went wrong

We're having trouble playing this video.

[Learn more](https://www.facebook.com/help/396404120401278/list)

Apps with access to certain types of Platform Data from Meta are required to complete the annual Data Protection Assessment (DPA). DPA is designed to determine whether developers meet the requirements of [Meta Platform Terms](https://developers.facebook.com/terms/dfc_platform_terms/) as it relates to the use, sharing, and protection of Platform Data. A subset of the DPA questionnaire is focused on Platform Term 6, which outlines data security requirements. We recommend you utilize this document to understand the expectations, requirements, and related evidence with respect to data security use and processing as defined in Meta Platform Terms.

Please note there is a [glossary](#glossary) included at the end of this document with key terms and definitions.

Find more video resources from [Data Protocol](https://l.facebook.com/l.php?u=https%3A%2F%2Fapp.dataprotocol.com%2Fchannels%2Fmeta&h=AUBcqLQa9HGmmLk0mY7vcBmy61ZH4PA5p-CkhEp5J6r2gjlHqa4dccAh1fqX8qNkfPuZ9nhZWvv3M4GfCip7yP-SIaTic10hNT9wi8QBCvNzawvDNkjZkaqCDX6hUhJKswWz6VWy9EYQBUpt).

Throughout this document, the phrase **server side** is used as a shorthand for any backend environment that an organization uses to process Platform Data, whether running on a cloud host like Amazon Web Services (AWS), hosted by the developer in a shared or exclusive data center, or a hybrid (combination of these).

**Client side** requirements refer to processing Platform Data within browsers, mobile devices, within apps on desktop and laptop computers, and other types of devices used by people.

## Preparing to Answer Data Security Questions

### Data Flows

Create (or update, if necessary) a data flow diagram or description that illustrates how the app or system processes Platform Data.

1. **Client side** - Include all client software, such as browsers, mobile devices, and any other supported device types.
2. **Server side** - Include any related server or cloud environment(s) and identify:

1. The components where Platform Data:

1. Enters or exits the server environment(s) (e.g., web listeners and REST APIs)
2. Is written to persistent or durable storage such as databases, disks, or log files

2. The hosting model, for example:

1. **Self hosted** - an organization’s own servers running in an owned or shared data center.
2. **Infrastructure as a Service (IaaS)** - Such as [AWS EC2](https://l.facebook.com/l.php?u=https%3A%2F%2Faws.amazon.com%2Fec2%2F&h=AUArykvZ3vWmW0N_FrGLrKb4EoeqBVn5pTqjLqY_X5YEMnTPYnuwTMG1mMJHRF98b5LJMdayp-yJwLRpvy4cymk_iZ4cN3s9CnpET_r81gmIpjB7o4ey7uzhpPoSHZtoWmJ0-5N3ibm8TWou), Microsoft Azure IaaS, and Google Compute Engine.
3. **Platform as a Service (PaaS)** - such as AWS Elastic Beanstalk, Google App Engine, Force.com.
4. **Backend as a Service (BaaS)** - such as AWS Amplify, Azure Mobile Apps, Firebase, and MongoDB Switch.
5. **Hybrid** - some combination of the above models.

In the end, the data flow diagram or description should include:

1. Where Meta API access tokens are generated and transmitted / stored / renewed, in both client and server software (if applicable to the system design)
2. How you fetch Platform Data from Meta’s APIs, specifically focussing on Personally Identifiable Information (PII) like a person’s name, email address, gender, birthdate and other user data
3. How you use, store, and transmit this data
4. Any 4th parties to which Platform Data is sent

## Preparing Evidence

You may be required to submit evidence to support the answers related to data security protections that you implement. We recommend that you read the Evidence Guide in this document for examples of acceptable evidence and prepare the evidence accordingly. We accept common document file types along with screenshots and screen recordings. Please ensure files are not password protected. You can upload multiple files, maximum 2 GB each. We accept .xls, .xlsx, .csv, .doc, .docx, .pdf, .txt, .jpeg, .jpg, .png, .ppt, .pptx, .mov, .mp4, .zip and .zipx.

Please ensure that you [redact (remove) sensitive data from the evidence](#redact-evidence) before submitting it.

### Types of Evidence

For apps that are asked to upload evidence related to data security protections, Meta requires two different types of documentation:

1. **[Policy or Procedure Evidence](#policy-procedure-evidence)** - A policy or procedure document that explains the data security approach for [this protection]
2. **[Implementation Evidence](#implementation-evidence)** - Evidence from the system or application, such as a tool configuration or screen capture, that shows how you've implemented a given protection

#### Policy or Procedure Evidence

Policy or procedure evidence, sometimes referred to as an administrative control, is written documentation that describes the approach for a particular data security protection. The form of this evidence can vary – it could be an excerpt from a set of internal policies, part or all of an internal wiki page, or a newly-created document that you use to describe the approach if you do not have any pre-existing documentation. In any case, the policy or procedure evidence you upload must clearly explain how the approach for a given protection relates to Meta’s requirements. Please only provide the policy or language that is relevant and necessary for Meta’s security review, or use the free-text box associated with the question to direct our reviewers to the relevant section(s).

#### Implementation Evidence

Implementation evidence illustrates how you have implemented the policy or procedure in practice directly via a screenshot or screen recording. Because different developers have different configurations, we cannot provide examples for every scenario. That said, the implementation evidence should demonstrate the same level of detail as the examples we have provided to the extent possible.

### Completeness of Evidence

We understand that it may be unduly burdensome to prepare **implementation** evidence that comprehensively demonstrates implementation of a given data security protection. With that in mind, you should submit evidence according to the guidance here, taking care to [redact sensitive information from the evidence](#redact-evidence) before submitting it:

1. **[**Policy or Procedure Evidence**](https://developers.facebook.com/docs/development/maintaining-data-access/data-protection-assessment/data-security#policy-procedure-evidence) must clearly meet or exceed Meta’s requirements**

1. Meta will review the policy or procedure evidence for statements that align with Meta’s requirements for the given protection.
2. You should annotate the document to highlight relevant sections
3. For example, relevant to the protection Enable TLS 1.2 encryption or greater for all network connections where Platform Data is transmitted, acceptable evidence would include a document that clearly states:

1. Platform Data from Meta must never be transmitted across untrusted networks in unencrypted format
2. All web listeners (e.g., internet-facing load balancers) that receive or return Platform Data will be configured such that TLS 1.2 is enabled
3. All web listeners that receive or return Platform Data will be configured such that the following are disabled: SSL v2, SSL v3, TLS 1.0, and TLS 1.1

2. [**Implementation Evidence**](https://developers.facebook.com/docs/development/maintaining-data-access/data-protection-assessment/data-security#implementation-evidence) must show one or more examples of each policy or procedure’s implementation

1. You must upload one or more document, screenshot, or tool configuration that demonstrates how you have implemented each protection
2. Meta will review the implementation evidence to make sure it is aligned with the policy or procedure evidence
3. For example, relevant to the protection [Enable TLS 1.2 encryption or greater for all network connections where Platform Data is transmitted,](https://developers.facebook.com/docs/development/maintaining-data-access/data-protection-assessment/data-security#prot-platform-data) acceptable evidence would include the Qualys SSL test report for one of the web domains that is configured according to the policy or procedure.

### Sensitive Data You Should Redact from Evidence

Do not submit evidence that contains any of these values in readable (unredacted) form. If you are using an image editor for a screenshot, overlay a black box over the value. If you are using a PDF editor, make sure you are redacting the text by using a tool that actually removes the values rather than simply adding a layer while preserving the text (e.g., the redact tool in Apple’s Preview app).

* Health data
* Financial data
* IP Addresses
* Passwords, credentials, and access tokens
* Encryption keys
* Physical Addresses
* Personally Identifying Information (PII) about a natural individual (not to include businesses or other enterprise organizations), employees or other affiliates that could identify that individual directly or indirectly, such as:
  + Name
  + Email addresses
  + User IDs
  + Birthdates
  + Location data
  + Health data
  + Cultural, social, political identity
  + Data that could be otherwise identifiable to an individual in the specific context of the evidence
* Detailed reproduction steps for vulnerabilities (e.g., in a penetration test report)
* Data that developers know or reasonably should know is either from or about children under the age of 13

## Protecting Platform Data Stored Server Side with Encryption at Rest

**Question**: Do you enforce encryption at rest for all Platform Data stored in a cloud, server, or data center environment?

### Intent

Encryption at rest protects Platform Data by making the data indecipherable without a separate decryption key. This provides an additional layer of protection against unauthorized read access.

* On servers or in a cloud environment - where Platform Data related to all of an app’s users tends to be concentrated - encryption at rest reduces the risk of a data breach
* For example, encryption at rest protects against threats like an unauthorized access to a database backup, which may not be protected as tightly as the production database itself

### Summary of Requirements

If you do store Platform Data server side:

* You MUST protect that data:
  + With encryption at rest, or
  + With acceptable alternative protections (see [Acceptable Alterative Protections](#aap))


* Specific to the type of encryption used:
  + Either application-level (e.g., software encrypts/decrypts specific columns in a database) or full-disk encryption are acceptable
  + Although we recommend that industry-standard encryption (e.g., AES, BitLocker, Blowfish, TDES, RSA) be used, we do not require any particular algorithm or key length

If developer does NOT store Platform Data server side, **this requirement is not applicable**.

### Special Cases

#### Server Side Storage using IaaS, Self Hosting, or Hybrid Hosting

If you store Platform Data using IaaS hosting (e.g., AWS EC2, Microsoft Azure IaaS, and Google Compute Engine), self hosting, or a hybrid approach then this question does apply.

#### Server Side Storage using SaaS, PaaS, or BaaS Products

However, there are other backend hosting models that are special cases:

If you store Platform Data only via any of these (and not using IaaS, Self Hosting, or Hybrid Hosting), this question does not apply. You should instead describe this relationship in the **Service Provider** section of the DPA.

* **BaaS** - e.g., AWS Amplify, Azure Mobile Apps, Azure Playfab, Google Firebase, and MongoDB Switch
* **PaaS** - e.g., AWS Elastic Beanstalk, Google App Engine, Force.com
* **SaaS** - e.g., MailChimp or Salesforce

#### Server Side Storage using Meta APIs

If you store Platform Data only via a Meta API, for example using `player.setDataAsync()`, in the Instant Games SDK, this question does not apply.

### Evidence Guide

If you are asked to submit evidence for this protection, follow the instructions in [Preparing Evidence](#evidence-prep) to prepare both policy/procedure and implementation evidence.

### Example Implementation Evidence

#### AWS RDS

[AWS RDS](https://l.facebook.com/l.php?u=https%3A%2F%2Faws.amazon.com%2Frds%2F&h=AUBXMuyKPtvCizR9bp4oE9kqI5DAIYElz59lj5ZwrfjyFdDuvAikl7zENNGHPDK0QsVNtvngOK1GDbVhu8hukQg_Unmdq28QHcKqFBTQzUQ_KR3PlfA5mhd31ib9_djY9eeWyKhpawzPVtBF) - encryption at rest is configurable in AWS RDS, so developers must make sure that the configuration option is set to apply this protection.

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

#### AWS DynamoDB

[AWS DynamoDB](https://l.facebook.com/l.php?u=https%3A%2F%2Faws.amazon.com%2Fdynamodb%2F&h=AUAdNzCTcfWkrdvoyQitkUT74HlKNv3wjfQkZ_3bd7ub5kNieII9FLS_Nm0N2uxs0ykux8CdmjyAYw7S3ZPqjorqpIWZ1R5NhdPuCXYw4Z58xB2JXt-RG0IpVHjQWMYAV88urY17a0q-S7tO) is encrypted at rest by default. You can fetch the encryption at rest configuration for a table using these commands.

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

#### AWS DocumentDB

[AWS DocumentDB](https://l.facebook.com/l.php?u=https%3A%2F%2Faws.amazon.com%2Fdocumentdb%2F&h=AUAomKL3aJnaxTBiM2Kn9du1b7y8N4-23nPpQ2w9oraFBO1yBgUzB9VSddCB3zhZP5Zq9Ddf5n70In_0JIyuZM78Zrct8EeQVFMgbOczp60odsg5gtoG1AFmUPYnUOC8j_XW-hH99iwDP1Ck) must be configured to apply encryption at rest. For a representative cluster that contains Platform Data, use these commands to fetch the StorageEncrypted configuration.

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

#### AWS S3

[AWS S3](https://l.facebook.com/l.php?u=https%3A%2F%2Faws.amazon.com%2Fs3%2F&h=AUDnM1auxVbFIVvJKAhBQX9DCVRXDLnzteLlmjqE8KV9Lc-yclPjwv-sQ7e3Ak8pRH3-GIZDIsdfa3h-C6QaSXABG7_FwK_d68Q6e5txmcXUJwh3aU3EUZgR98vLuZUVlES3uK9rjOF20dex) buckets may be configured to apply encryption at rest to all objects created within the bucket. Use these commands to list buckets and fetch the configuration for default bucket encryption.

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

#### Microsoft Azure

Consult [Microsoft’s documentation on encryption at rest in Azure](https://l.facebook.com/l.php?u=https%3A%2F%2Fdocs.microsoft.com%2Fen-us%2Fazure%2Fsecurity%2Ffundamentals%2Fencryption-atrest&h=AUBY2F7j-YhFqfJg7PPBNIJH6kNWSNyZbA04IBSxN3ecjGfmAWZ7_tEtklxRAqmjZIyszknTa6CHDtAMJbRaGjDtx8K5-kSfX3MKsXXHhLj08GYSlgfQwSluEu2Y3Lnur4oV7Biuf--PXaom) that’s relevant to the organization’s use of their services.

#### Google Cloud Platform

Consult [Google’s documentation on encryption at rest on Google Cloud Platform](https://l.facebook.com/l.php?u=https%3A%2F%2Fcloud.google.com%2Fdocs%2Fsecurity%2Fencryption%2Fdefault-encryption&h=AUC58Xf82iAMYKwrbYBLAqWFpgdhxjeGQz-MqJrqaPy__KRqTPoZ-WQxhgk0tTejMUEqaOiBRnE7pMqeP5y7xF2RSsF1CeFmDZsb5vN9n171pHGK7-Uzl1ZNQQmtlS6D7zWFm5qCXd4ZgUtY).

### Acceptable Alternative Protections

If you do not implement encryption at rest in the server side environment, you may be protecting Platform Data in an alternative way that is still acceptable. In this case, you should describe the following:

1. **Sensitivity of the Platform Data** - Storage of specific Platform Data is considered lower or higher risk. You will need to research which specific platform data user attributes are being stored server side.
2. **Controls Applied to Reduce Likelihood of Specific Harms**

1. Controls to prevent compromise of networks containing Platform Data
2. Controls to prevent compromise of apps/systems having access to Platform Data
3. Controls to prevent loss of physical storage media (e.g., decommissioned network storage devices) containing Platform Data
4. Controls to prevent unauthorized access to backup copies of storage containing Platform Data backups

3. **Strength of Evidence** - be sure to note if these protections have been evaluated by an independent auditor, for example as part of a SOC2 audit.

## Protecting Platform Data Stored on Organizational Devices and Removable Media from Loss

**Question**: Specifically concerning data stored on organizational and personal devices: Do you enforce encryption at rest, or do you have in place policies and rules to reduce the risk of data loss, for all Platform Data stored on these devices?

### Intent

If a developer allows Platform Data on devices like employee laptops or removable storage (e.g., USB drives), that data is at high risk of unauthorized access if the device is lost or stolen. Developers should take steps to limit this risk.

### Summary of Requirements

* To reduce the risk of unauthorized Platform Data access, Developers must have either technical controls (preferred) or administrative controls (not preferred, but acceptable) relevant to Platform Data on organizational devices (e.g., laptops) and removable media.

  + **Technical controls** - examples of technical controls include: 1) Allowing only managed devices to connect to the corporate network, 2) enforcing full disk encryption on managed devices (e.g., BitLocker), 3) Blocking removable media (e.g., USB drives) from being connected to managed devices, 4) using Data Loss Prevention (DLP) technology on managed devices.
  + **Administrative controls** - examples of administrative controls include written policy documentation and annual training about acceptable ways to handle Platform Data on organizational and personal devices.

This requirement applies whether or not you process Platform Data server side.

### Evidence Guide

If you are asked to submit evidence for this protection, follow the instructions in [Preparing Evidence](#evidence-pre) to prepare both policy/procedure and implementation evidence.

You may be using one or both of: a) technical controls (e.g., disk encryption), or b) rules/policies to reduce the risk of data loss for Platform Data being stored on organizational devices like laptops and mobile phones.

Technical controls might include:

* Blocking unmanaged devices from connecting to sensitive services, such as the production network
* Enforcing disk encryption on managed devices (e.g., via BitLocker on Windows or FileVault on Mac)
* Blocking removable media from use (e.g., USB drive) on managed devices
* Using DLP software on managed devices to block improper handling of Platform Data (e.g., sending it in an email attachment)

Rules/policies might include:

* Documentation that describes acceptable and unacceptable ways of handling data, in general, and Platform Data in particular
* A mechanism to cause organization members to be aware of the guidelines (e.g., contractual agreement as a condition of employment, training, periodic reminders via email)

### Example Evidence

An organization classifies Platform Data from Meta as “private data” according to their data classification standard. The organization has created Data Handling Guidelines and obligates all personnel to understand and abide by these policies.

![](https://scontent-eze1-1.xx.fbcdn.net/v/t39.8562-6/297386451_1304030650334733_4012168579059819218_n.png?_nc_cat=102&ccb=1-7&_nc_sid=f537c7&_nc_ohc=gRg5VB65kAAQ7kNvwGbQ4qW&_nc_oc=Ado1HrmLyXt0BgYFi3FZUwIb6FEk9V61fwf63stQVxWa7-tERRzkeLVLxnDtW1jIENU&_nc_zt=14&_nc_ht=scontent-eze1-1.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQBbYa6koXV0k60UfIlfuX8RBeN8RFK6cliffK99GMlCtw&oe=6A68D14B)

## Protecting Platform Data Transmitted Over Networks with Encryption in Transit

**Question**: Do you enable security protocol TLS 1.2 or greater for all network connections that pass through, or connect, or cross public networks where Platform Data is transmitted?
Additionally, do you ensure that Platform Data is never transmitted over public networks in unencrypted form (e.g., via HTTP or FTP) and that security protocols SSL v2 and SSL v3 are never used?

### Intent

Platform Data transmitted across the internet is accessible to anyone that can observe the network traffic. Therefore it must be protected with encryption to prevent those unauthorized parties from being able to read the data.

* Encryption in transit protects Platform Data when it is transmitted across untrusted networks (e.g., the internet) by making it indecipherable except for the origin and the destination devices
* In other words, parties in the middle of the transmission would not be able to read Platform Data even if they can see the network traffic (this is also called a man-in-the-middle attack)
* TLS is the most prevalent form of encryption in transit because it’s the technology that browsers use to secure communications to websites like banks

### Summary of Requirements

Whether or not you processes Platform Data server side:

* Platform Data must never be transmitted across untrusted networks in unencrypted format
* For all web listeners (e.g., internet-facing load balancers) that receive or return Platform Data, you must:
  + Enable TLS 1.2 or above
  + Disable SSL v2 and SSL v3
* TLS 1.0 and TLS 1.1 may only be used for compatibility with client devices that are not capable of TLS 1.2+
* Meta recommends, but does not require, that encryption in transit be applied to transmissions of Platform Data that are entirely within private networks, e.g., within a Virtual Private Cloud (VPC).

The table below summarizes encryption in transit policy for different transmission types.

Type of Transmission | Encryption in Transit Policy || To and from end user devices (mobile phones, PCs, tablets, etc.) and the server or cloud infrastructure. | * TLS 1.2 or greater must be enabled for compatible devices * TLS 1.0 and 1.1 may be enabled for compatibility with older devices |
| To and from the server or cloud infrastructure and any remote server, cloud infrastructure, or 4th party service. | TLS 1.2 or greater must be enforced |
| To and from components entirely within the private data center, server, or cloud infrastructure | TLS encryption is recommended but not required for Platform Data transfers that are entirely within a private cloud network |
| To and from Meta and any device, server, or cloud infrastructure | Out of Scope for Data Protection Assessment - Meta controls the TLS policy for these transfers |

### Evidence Guide

If you are asked to submit evidence for this protection, follow the instructions in [Preparing Evidence](#evidence-pre) to prepare both policy/procedure and implementation evidence. A straightforward way to produce implementation evidence that demonstrates the configuration of one of the web listeners is to use the Qualys SSL Server Test tool.

* Run the [Qualys SSL Server Test tool](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.ssllabs.com%2Fssltest%2F&h=AUCg8rcKrmx474QciI_-1pjZorar9yL6ih8oZ48eSVP3NmtvE09BiovQcDbDMhNgPbJ3VtlyZ9NGLW5ao1WVzLRQ-kdgyCUB68hAj76HcUT8bS6ilWkLlqUtDLjA1HAwP5cHkyh9CVO6fC2j) against one or more of the web listeners that are configured identically (including any that run on nonstandard ports).
* Tick the "Do not show the results on the boards" option to prevent the results from being added to the Qualys website.
  Print the entire test result(s) page to PDF
  Repeat the above steps for any web listeners that you transmit Platform Data to/from that that have a different TLS configuration

### Example Implementation Evidence

This is an example output from the Qualys SSL Server Test tool. Note the red annotations in the Configuration section, which summarizes which SSL/TLS versions are supported. Note: this example includes only the first two pages but you should include the full test output.

![](https://lookaside.fbsbx.com/elementpath/media/?media_id=749130786299921&version=1726710699)![](https://lookaside.fbsbx.com/elementpath/media/?media_id=647596009598476&version=1726710699)

### Acceptable Alternative Protections

You may be protecting Platform Data in transit using a different type of encryption besides TLS; this may be acceptable if the approach provides equivalent protection. In this case, you should submit details about the encryption used for Meta to review:

* Symmetric or asymmetric encryption?
* Encryption algorithm (e.g., AES, BitLocker, TDES, RSA)?
* What is the minimum key length?

## Test the App and Systems for Vulnerabilities and Security Issues

**Question**: Do you [test the app and systems for vulnerabilities and security issues](https://developers.facebook.com/docs/development/maintaining-data-access/data-protection-assessment/faq#security-tests) at least every 12 months? (For example, do you perform a manual penetration test?)

### Intent

Developers must test for vulnerabilities and security issues so that they can be discovered proactively, ideally preventing security incidents before they happen

* App developers that use Meta’s platform to process Platform Data with software they write via apps/systems that they configure and operate
* Software and system configurations may contain security vulnerabilities that malicious actors can exploit, leading to unauthorized access to Platform Data

### Summary of Requirements

Applicable to all developers:

* You must have tested the software used to process Platform Data for security vulnerabilities by either conducting:
  + A penetration test of the app/system, or
  + A vulnerability scan/static analysis of the software
* The output of the test must show that there are no unresolved critical or high severity vulnerabilities
* The test must have been completed within the past 12 months

Additional requirements for developers that process Platform Data server side:

* You must have specifically tested server side software for security vulnerabilities by either conducting:
  + A penetration test of the app/system, or
  + A vulnerability scan/static analysis
    You must have also tested the cloud configuration for security issues if you are using a cloud hosting provider
    This requirement applies irrespective of the hosting approach (e.g., BaaS, PaaS, IaaS, self hosted, or hybrid)

If the organization is considering adding SAST to the development process, [NIST maintains a list of open source and commercial tools](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.nist.gov%2Fitl%2Fssd%2Fsoftware-quality-group%2Fsource-code-security-analyzers&h=AUDBvpD-Ty6S_KaqhyHJeJneJJ854CKZpSjgg6Itil2rlHVrRkmK-VcLwX1eHz5qIqRLBDMyzQCExePheNrZty5Nbf729kLCmUkAfzARQz17A5fljYJVDYgAPXoFaMXUNcMSj6iSuuYFzZZH) that you may find a useful starting point for choosing a tool.

### Evidence Guide

If you are asked to submit evidence for this protection, follow the instructions in [Preparing Evidence](#evidence-pre) to prepare both policy/procedure and implementation evidence.

If the organization processes Platform Data in a cloud or server environment:

* Submit evidence that a penetration test or SAST tool execution has been completed. The evidence should contain:
  + A statement of the scope of the test
  + The date that the test was completed – the date should be within the past 12 months
  + Either a summary or a listing of the vulnerabilities discovered during the test. The summary or listing must include severity categorization (e.g., critical, high, medium, low, informational). Typically we would expect that there are no unresolved critical or high severity vulnerabilities

The internet-accessible cloud or server software (e.g., a REST API used by web and mobile clients) you use to process Platform Data must be in the scope of this test for it to be acceptable.

* If applicable (i.e., if you’re using a cloud host like AWS, GCP, Azure, or similar) submit evidence that a cloud configuration review has been undertaken, for example the output of a run of [NCC Scout Suite](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Fnccgroup%2FScoutSuite&h=AUAl6PuSXFpn70HO0NaPLKA7aGZ6LVj6XW8e7TugMI_9C0J4mZGO045HSggnscopANRR56eMrFw9qPxANvpzFtGvACjUlcjmgsNdcBOhMqCKkgehticzWVAPOk3stokQtajRKRjXhFuT6lYS), [AWS Config](https://l.facebook.com/l.php?u=https%3A%2F%2Faws.amazon.com%2Fconfig%2F&h=AUCA51InZHFyyN6jJwLnD6QfLBh32YoVNE7v-b0FMbat3b47gGNnRO1prWyJgoWcO0xUIQ1lwNxrcBDRw3-ZDT1ZYf99l-Y4_GXM1CV8HXh-5nBBhZGkLA2dPCB5oJF9sUpML1xGfX2w_X0U) or similar. If this is not applicable to the organization, include in the evidence submission a document that explains why a cloud configuration review is not applicable.
* **[Remove or redact sensitive information](#redact-evidence) like detailed vulnerability reproduction steps from the evidence before submitting**

If the organization does NOT process Platform Data in a cloud or server environment:

* Submit evidence that a penetration test or SAST tool execution has been completed. The evidence should contain:
  + A statement of the scope of the test
  + The date that the test was completed – the date should be within the past 12 months
  + Either a summary or a listing of the vulnerabilities discovered during the test. The summary or listing must include severity categorization (e.g., critical, high, medium, low, informational). Typically we would expect that there are no unresolved critical or high severity vulnerabilities.
* **[Remove or redact sensitive information](#redact-evidence) like detailed vulnerability reproduction steps from the evidence before submitting**

### Example Evidence

**Penetration Test** - An organization commissions a penetration test of their software running server side that integrates with Meta APIs and processes Platform Data. The test firm completes the test and produces a summary letter like the one below. Note the red annotations, which highlight that the date when the test took place is denoted (must be within past 12 months) and there is a summary of the unresolved critical/high severity findings at the conclusion of testing (or retesting, if applicable). Please [redact sensitive information](#redact-evidence) from the report (in particular, any detailed vulnerability reproduction steps) before submitting it.

![](https://scontent-eze1-1.xx.fbcdn.net/v/t39.8562-6/297723361_470172984524680_7234147365069664055_n.png?_nc_cat=102&ccb=1-7&_nc_sid=f537c7&_nc_ohc=lDcLi8IJDqYQ7kNvwEr-VOL&_nc_oc=Adon9S9gbdoBKq1MOgWQGOTOcW8jHryvOtcLvl5AZoPD_g5Z2k1XiP0VPiwtmK0fKj0&_nc_zt=14&_nc_ht=scontent-eze1-1.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQDY20ZS5ND3eNZA5BICiz5S6_aIr0c0VoRPlmVTQTAw6g&oe=6A68AA89)![](https://scontent-eze1-2.xx.fbcdn.net/v/t39.8562-6/297458832_742087616871124_3954880147266738171_n.png?_nc_cat=107&ccb=1-7&_nc_sid=f537c7&_nc_ohc=TPUcvptGsWwQ7kNvwGCNqC4&_nc_oc=AdqVoNvNXaO9eotpfKwqJaCiJlFn_zNF5sZMsu_Pt1SjKDgQR6Xm0l8neWmRVohbMkg&_nc_zt=14&_nc_ht=scontent-eze1-2.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQCGd0t3U8jP5JGlm3Rh3BFvMfJk2UoYyR_5fVTQdr4Gsg&oe=6A68A29C)

**Static analysis** - If using a different approach, for example a SAST tool, export the results into a document that includes the SAST run date and a list of findings that includes each finding’s type and its severity/criticality.

**Cloud Configuration Review**

A developer uses [NCC Scout Suite](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Fnccgroup%2FScoutSuite&h=AUC9tOmSvb5K20ufoQyiKQCmFRYLzyCHIOykkaE-7RfDNKwiywgQYJI_JSlV2A6lXbTld1vsfUVCNl9J72ajfd_-tk1dKegbP4XPD46LfUzjnsbrUaB7XzrnZIwkFnmI8xI-2VDef84wPNN2) using the default ruleset for their cloud provider (in this case, AWS) to review their cloud configuration for vulnerabilities and security issues. The tool outputs a JSON file containing the detailed run results. In this example, there are a number of issues flagged as “Danger” severity that the developer needs to review and resolve.

The raw NCC Scout Suite JSON file contains details about your cloud environment that you should not upload. Instead, filter the responses to show the count of findings by severity.

```
$ python3 scout.py aws –-no-browser
2022-08-22 11:39:38 localhost scout[76981] INFO Saving data to scoutsuite-report/scoutsuite-results/scoutsuite_results_aws-043954759379.js

$ cd scoutsuite-report/scoutsuite-results
$ tail -n +2 scoutsuite_results_aws-043954750000.js| jq '. | {last_run}' | pbcopy

{
  "last_run": {
    "ruleset_about": "This ruleset consists of numerous rules that are considered standard by NCC Group. The rules enabled range from violations of well-known security best practices to gaps resulting from less-known security implications of provider-specific mechanisms. Additional rules exist, some of them requiring extra-parameters to be configured, and some of them being applicable to a limited number of users.",
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
      "cloudfront": {
        "checked_items": 0,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 0,
        "rules_count": 3
      },
      "cloudtrail": {
        "checked_items": 153,
        "flagged_items": 4,
        "max_level": "danger",
        "resources_count": 17,
        "rules_count": 9
      },
      "cloudwatch": {
        "checked_items": 2,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 2,
        "rules_count": 1
      },
      "codebuild": {
        "checked_items": 0,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 0,
        "rules_count": 0
      },
      "config": {
        "checked_items": 17,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 1227,
        "rules_count": 1
      },
      "directconnect": {
        "checked_items": 0,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 0,
        "rules_count": 0
      },
      "dynamodb": {
        "checked_items": 0,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 1,
        "rules_count": 0
      },
      "ec2": {
        "checked_items": 760,
        "flagged_items": 108,
        "max_level": "danger",
        "resources_count": 44,
        "rules_count": 28
      },
      "efs": {
        "checked_items": 0,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 0,
        "rules_count": 0
      },
      "elasticache": {
        "checked_items": 0,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 0,
        "rules_count": 0
      },
      "elb": {
        "checked_items": 0,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 0,
        "rules_count": 3
      },
      "elbv2": {
        "checked_items": 42,
        "flagged_items": 4,
        "max_level": "danger",
        "resources_count": 0,
        "rules_count": 5
      },
      "emr": {
        "checked_items": 0,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 0,
        "rules_count": 0
      },
      "iam": {
        "checked_items": 801,
        "flagged_items": 27,
        "max_level": "danger",
        "resources_count": 87,
        "rules_count": 37
      },
      "kms": {
        "checked_items": 15,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 15,
        "rules_count": 1
      },
      "rds": {
        "checked_items": 1,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 27,
        "rules_count": 9
      },
      "redshift": {
        "checked_items": 0,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 0,
        "rules_count": 6
      },
      "route53": {
        "checked_items": 0,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 1,
        "rules_count": 3
      },
      "s3": {
        "checked_items": 121,
        "flagged_items": 34,
        "max_level": "warning",
        "resources_count": 7,
        "rules_count": 18
      },
      "secretsmanager": {
        "checked_items": 0,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 1,
        "rules_count": 0
      },
      "ses": {
        "checked_items": 0,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 0,
        "rules_count": 4
      },
      "sns": {
        "checked_items": 0,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 0,
        "rules_count": 7
      },
      "sqs": {
        "checked_items": 0,
        "flagged_items": 0,
        "max_level": "warning",
        "resources_count": 0,
        "rules_count": 8
      },
      "vpc": {
        "checked_items": 271,
        "flagged_items": 211,
        "max_level": "warning",
        "resources_count": 0,
        "rules_count": 9
      }
    },
    "time": "2022-08-22 11:42:25-0400",
    "version": "5.11.0"
  }
}
```


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

### Acceptable Alternate Protections

If you are operating a functioning Vulnerability Disclosure Program (VDP), e.g., using the [BugCrowd](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.bugcrowd.com%2Fglossary%2Fvulnerability-disclosure-program-vdp%2F&h=AUBYLeJJcSxDric-afi7yEvnUX4FyE02PqbcylPrJZXmVCKqiUNt02mxLUB9ssVJEWe0UDKbbcbqVxIkZR0fcOqIJbHdcx5ZEpfb5YYw-_o0pouNxMafma0RReJi94m37yamZhqqq3CeOvkg) or [HackerOne](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.hackerone.com%2Fproduct%2Fresponse-vulnerability-disclosure-program&h=AUAROJ32O8SsM-tqYXMuwycJT1L0HTuv9Z9IOsMZt6GvxnPgaKadAjMfZT7mGOr_k9mwR7iRlfufN_DH4KDU41CyzMVod8llPvimTpGVJUKY4etx4t2pBeJx6sN5s4AzRtSw4y7F1t1o-5Kx) platforms, you may present this as an alternative protection instead of a pen test or vulnerability scan. To demonstrate this, you must submit evidence that:

* There are no exclusions to the scope of the VDP relevant to the way you process Platform Data
* There is actual ongoing vulnerability research and reporting within the past 12 months, typically indicated by at least 1 valid vulnerability report per month
* Submitted (valid) vulnerabilities are assigned a severity score, e.g., using CVSS 3.1
* Vulnerabilities are resolved in a reasonable amount of time, typically fewer than 90 days after the submission date

In this case, the evidence should include:

* A statement of scope and how that interrelates with the software used to process Platform Data
* And a report of the actual vulnerability submissions in the program over the past 12 months. The report should include the vulnerability title, submission date, resolution date (if resolved) and severity category / score.

## Protect the Meta App Secret and API Access Tokens

**Question**: Are Meta API access tokens and app secrets protected in both of the following ways?

1. By never storing Meta API access tokens on client devices where they are accessible outside of the current app and user.
2. By using a data vault (e.g., Vault by Hashicorp) with separate key management service (KMS) if these are stored in a cloud, server or data center environment.

### Intent

App secrets and access tokens are fundamental to the security of how Meta APIs make decisions about what actions to allow. If an unauthorized party gains access to these credentials they could call Meta APIs - impersonating the real developer - and take any of the actions that we have granted the app (e.g., reading data from Meta APIs about an app’s users).

* You have access to sensitive credentials as a part of the use of Meta’s Platform. Specifically:
  + **Access Token** - When people authorize the app, the software gets a credential called an access token that’s used in subsequent API calls
  + **App Secret** - Meta shares an app secret with developers with the expectation that only trusted parties (e.g., app admins) within the organization have access to this secret
* An unauthorized party who is able to read these sensitive credentials can use them to call Meta APIs as if they are you (this is sometimes called token impersonation) leading to unauthorized access to Platform Data
* Therefore these credentials must be protected from unauthorized access to prevent impersonation

### Summary of Requirements

**Access Tokens**

1. **On client devices** - Meta access tokens must not be written such that another user or process could read it.
2. **Server sides - If you process or store Meta access tokens server side, those access tokens:**

1. Must be protected using a data vault (e.g., Vault by Hashicorp) with separate key management service (KMS) and where access to the decryption key is limited to the application
2. Must not be written to log files

**App Secret** - one of these two things must be true:

1. You never expose the app secret outside of a secured server environment (e.g., it is never returned by a network call to a browser or mobile app and the secret is not embedded into code that’s distributed to mobile or native/desktop clients)
2. Or you must have configured the app with [type Native/Desktop](https://developers.facebook.com/docs/development/create-an-app/app-dashboard/advanced-settings/) so that Meta APIs will no longer trust API calls that include the app secret

### Evidence Guide

If you are asked to submit evidence for this protection, follow the instructions in [Preparing Evidence](#evidence-pre) to prepare both policy/procedure and implementation evidence.

Include documentation about the policy for protecting Meta API access tokens and the app secret
If the app processes Meta access tokens server side, include evidence that demonstrates the protections that you take (e.g., use of a vault, demonstrating that values are stored in an encrypted format, configuration of the app to require appsecret proofs).

Make sure that you do not include (i.e., remove) the plaintext values of any secrets or access tokens in the evidence that you submit.

### Example Evidence

An organization uses AWS Secrets Manager to security store sensitive data, including the Meta App Secret.

![](https://scontent-eze1-1.xx.fbcdn.net/v/t39.8562-6/297506691_370693685140842_8016809687985858930_n.png?_nc_cat=111&ccb=1-7&_nc_sid=f537c7&_nc_ohc=inQaQGsSpyQQ7kNvwE09omU&_nc_oc=AdpUIw2fThgsHwL03BwF8mkSxdL7HyJ4K7s9EQV5CFHCjNaDRKlwPbPhndmowd4SR7c&_nc_zt=14&_nc_ht=scontent-eze1-1.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQD8Ks3ALfdDgs67EETaGiBlau5h2G8glQKTsyMax0NFYA&oe=6A68AC32)


An organization has configured its Meta app to require App Secret proof for API calls.

![](https://scontent-eze1-1.xx.fbcdn.net/v/t39.8562-6/296650418_786487619431440_4869070492354926095_n.png?_nc_cat=102&ccb=1-7&_nc_sid=f537c7&_nc_ohc=CXP_5WdtH_EQ7kNvwEyTLow&_nc_oc=AdpnInaffh-bGEB8KX67auUI2Y4PvXpjiFdHKGebWryFEAT_BsFPfHIWLlhSWTu3TTU&_nc_zt=14&_nc_ht=scontent-eze1-1.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQC9v1P7M9HgsVVUjAqp4hcsI7twT2IYr1PLiSsWhqSf9g&oe=6A68BA2D)

### Acceptable Alternative Protections

1. If you do not protect access tokens stored server side with a data vault or via app-level encryption, you may:

1. Protect the app secret by using a vault or application encryption where the key is only accessible to the app
2. And configure the app to [require appsecret proof for all API calls to Meta](https://developers.facebook.com/docs/graph-api/securing-requests%20/#require-proof)

2. If approach #1 above is not viable (i.e., cannot require appsecret proof because it would block certain necessary API calls), then Meta will consider any other controls that you have in place to limit the risk of unauthorized use of the access tokens compared to the the risk of misuse of stored access tokens

## Have an Incident Response Plan and Test the Incident Response Systems and Processes

**Question**: Do you test the systems and processes you would use to respond to a security incident (e.g., a data breach or cyberattack) at least every 12 months?

### Intent

Security incidents happen to all companies sooner or later, so it is essential that organizations have planned ahead for who needs to do what to contain the incident, communicate with stakeholders, recover and learn from what happened.

* If a security incident occurs, having a plan or playbook ready - with a team of people who are trained in what to do - can reduce the duration of the incident and ultimately limit the exposure of Platform Data
* Although different organizations will have different levels of incident response sophistication, we require at least a basic plan that includes the key activities - detect, react, recover, and review along with named personnel assigned roles and responsibilities

### Summary of Requirements

Developer must have:

* An incident response plan that meets Meta’s minimum criteria.
* This document must include (at least): (1) roles and responsibilities, (2) detection, (3) steps to react pursuant to applicable legal obligations (e.g. data breach notification to relevant supervisory authorities and data subjects) and recover, and (4) a post incident review process
* Documented evidence that the plan has been tested recently (within the past 12 months) and that all personnel named in the plan did participate

This requirement applies whether or not you process Platform Data server side.

### Evidence Guide

Follow the instructions in [Preparing Evidence](#evidence-pre) to prepare both policy/procedure and implementation evidence.

* Submit the incident response plan (one or more documents). It should contain the following topics: roles and responsibilities, detection, react and recovery, and post incident review
  + If you do not have an incident response plan, there are many resources available on the internet that may help, for example see Counteractive’s [incident response plan template](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Fcounteractive%2Fincident-response-plan-template&h=AUC8ZMTFDStbxURHKmEwKkUvbDXIY9JXW9sPw8DCf5diULfTWSFsJ3OB2kt9jOemzLNR0UHtaPzFElUMrQLrO3SbKMg4PhpUkiDKRbZx_xPTI4HRgXVEKMbm0MiWVKg8EnqMngeAr5Kl7ex2) and [References and Additional Reading](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Fcounteractive%2Fincident-response-plan-template%23references-and-additional-reading&h=AUCPPCiw9n67eb9DYbn_MEeJhnEtQqeBq1QWAtKMHezhV3uVFiwqr4o0CgGKahG5KKFGYdzC1Wl9Uf8kMKBufB72qdNycizg__zkkTKL-vksh4OY8tHvbQbXxN00ibFuaDKSi72YGMXYxUHc)
* Submit evidence that you have tested the plan within the past 12 months. This evidence may take different forms, but it should include:
  + A description of the scenario (e.g., a tabletop exercise in response to a ransomware attack),
  + The date when the test took place
  + The role of each participant and,
  + If any of the personnel named in the plan’s roles and responsibilities section did not participate, justification for each
* Please redact sensitive information (e.g. PII such as individual’s name and email address) from this evidence before submitting it
  Example Evidence

#### Incident Response Plan

A developer has created a comprehensive incident response plan based on this template. These images depict just the table of contents but there is a link below to the full template.

![](https://scontent-eze1-2.xx.fbcdn.net/v/t39.8562-6/297856713_5619986374718203_4542317399994563224_n.png?_nc_cat=104&ccb=1-7&_nc_sid=f537c7&_nc_ohc=ehpRyJxhU6AQ7kNvwHQSkK2&_nc_oc=Adrlf1g5HvdTCHXXDVycBF8TOvn34KTA--ARhdHeWin6l9ykmJAVnMM61-uMJhPMXtE&_nc_zt=14&_nc_ht=scontent-eze1-2.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQCOZfmampy3FvZIDd2ETXAh6WWrISWJPir6nGje2gTlAQ&oe=6A68AE58)

See the full [Counteractive incident response plan template (docx format)](https://l.facebook.com/l.php?u=https%3A%2F%2Fgithub.com%2Fcounteractive%2Fincident-response-plan-template%2Fblob%2Fmaster%2Fexamples%2Fplan.docx&h=AUDgcCx5BVNaEVD10Pufm83sQA7a3R8nca6H_zwi_AJVedTbBsJbp3ZPwhvIvAuVJ5Q7kKT9Yy1AAT9-_X1Ei8ZJLFPwH1srHkeMCC2WNvRlkj65sK5CERws8_62-QQ9Nt5Vw1a5lhuNgPMU)

#### Incident Response Test

A developer has conducted a test of their incident response plan via a tabletop exercise and documented the outcome based on this template.

Only the first two pages are included here, but you should submit the entire document.

![](https://scontent-eze1-1.xx.fbcdn.net/v/t39.8562-6/296783473_446236504097130_261841073863537671_n.jpg?_nc_cat=111&ccb=1-7&_nc_sid=f537c7&_nc_ohc=rpV8_u8cH38Q7kNvwFl7Xcf&_nc_oc=AdoFnIMn0DyveBNUj6D_TRHvmslNlcScULC2D_cS1U16bAKob0GBkURCBtC4nFt9okE&_nc_zt=14&_nc_ht=scontent-eze1-1.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQAbGoi2DzGSsiq4lkp0ObgO6_4d7CoBeAZe8IOYr1d_QQ&oe=6A68C58F)![](https://scontent-eze1-1.xx.fbcdn.net/v/t39.8562-6/297296727_440319691348882_2144329882083917761_n.png?_nc_cat=110&ccb=1-7&_nc_sid=f537c7&_nc_ohc=aAkHvl1Q4_IQ7kNvwGVPUxn&_nc_oc=Adqn-KGFx-lAg1fAZxAfbYsFO7GMWJ2CX8jxmtaK8Fd61qL7B_k4ZzmhViHXqkXgzKs&_nc_zt=14&_nc_ht=scontent-eze1-1.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQCJYgAKLxy2A5P8tOG87UJatBYJc48aHm6AkaYb3EAfUw&oe=6A68B45B)

## Require Multi-Factor Authentication for Remote Access

**Question**: Do you require [multi-factor authentication](https://developers.facebook.com/docs/development/maintaining-data-access/data-protection-assessment/faq#multi-fac-auth) for remote access to every account that is able to connect to the cloud or server environment and/or to access the services you use to deploy, maintain, monitor, and operate the systems where you store Platform Data from Meta?

### Intent

A common technique used by adversaries to gain access to confidential data is to start by gaining access to tools that a developer uses to build or operate their app/system. Sophisticated tools exist to hack into accounts that are protected only by passwords; multi-factor authentication provides an additional layer of security to guard against this risk.

* Software developers use a variety of tools to build, deploy, and administer their apps/systems
* It’s common to use these tools remotely over the internet (e.g., an employee working from home and shipping a new software feature or updating the cloud configuration)
* Tools that are protected with single factor authentication (username and password) are highly susceptible to account takeover attacks. For example, attackers can use tools to try username and password combinations that have leaked from one tool to gain access to another tool
* Multi-factor authentication protects against such attacks by requiring an additional factor besides a password upon login, e.g., a code generated by authenticator app

### Summary of Requirements

Related to an organization’s processing of Platform Data, remote access to these tools must be protected with multi factor authentication (i.e., not simply a password):

* Tools used to deploy and manage code/configuration changes to the app/system
* Administrative access to a cloud or server environment, if applicable

Specifically, MFA or an acceptable alternative protection is required for the following:

* **Collaboration / communications tools** - for example, business email or Slack
* **Code repository** - e.g., GitHub or another tool used to track changes to the app/system’s code/configuration
* And, if you process platform data server side:
  + **Software deployment tools** - tools used to deploy code into the cloud/server environment, e.g., Jenkins or another Continuous Integration / Continuous Deployment (CI/CD) tool
  + **Administrative tools** - portal or other access used to manage / monitor the cloud or server environment
  + **Remote access to servers** - SSH, remote desktop, or similar tools used to remotely login to servers running server side

Regarding the implementation of MFA:

* Use of an authenticator app or hardware (e.g., YubiKey) is recommended and preferred to codes sent by SMS
* But organizations can use any MFA implementation

### Evidence Guide

If you are asked to submit evidence for this protection, follow the instructions in [Preparing Evidence](#evidence-pre) to prepare both policy/procedure and implementation evidence.

* Implementation evidence should show that MFA is enforced on the tools applicable to the environment that are listed above (i.e., collaboration tools, code repository, cloud/server deployment, cloud/server administrative portal, cloud/server remote access)
* Implementation will vary depending on the configuration:
  + For example, if you’re using an SSO provider this may be a screenshot of a global configuration for the organization or a screenshot of a per-app configuration.
  + If you do not have an SSO provider, this may be a screenshot of the configuration of a particular tool
* In any case, we need evidence that MFA is enabled for all users and not just an example of an account with MFA enabled

### Example Evidence

#### AzureAD

An organization uses AzureAD as their Single Sign On solution. This policy requires Multi-Factor Authentication.

![](https://scontent-eze1-2.xx.fbcdn.net/v/t39.8562-6/297645744_5313396222109590_4384528416019988582_n.png?_nc_cat=100&ccb=1-7&_nc_sid=f537c7&_nc_ohc=8AS9cuiC_OIQ7kNvwGEB655&_nc_oc=Adp58rm_0tZGMY7aojIABAUMj5TjI37Zln4FCCRUDJK3auaoEMq7WI0uR5KZ_FxVEgU&_nc_zt=14&_nc_ht=scontent-eze1-2.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQCd_vqo_FFoZxH1a6qwh9WQN5RF6HzLRmg67j_llLFjlA&oe=6A68B31C)

The policy is then mapped to the cloud apps to which it applies. Using this approach, evidence should show the entire **Selected items** section to make it clear which cloud apps require MFA.

![](https://scontent-eze1-2.xx.fbcdn.net/v/t39.8562-6/297628661_414391590686225_5507528555677800242_n.png?_nc_cat=107&ccb=1-7&_nc_sid=f537c7&_nc_ohc=MsI8y4PF_lgQ7kNvwFV6FNN&_nc_oc=Adotqey8Uzm_RdnJ9lRWLLiPFYJ1_jb67DZTW5Kj0xM1xeno4N5kITTDn_jBwfArTp8&_nc_zt=14&_nc_ht=scontent-eze1-2.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQC0-FPTbCszYu8abclJ4oEiZM_0C-Ui5Y6u721IPje0lQ&oe=6A68AB19)


#### Okta

This rule requires MFA for all logins.

![](https://scontent-eze1-1.xx.fbcdn.net/v/t39.8562-6/297756140_1379147979279099_3252042437150556056_n.png?_nc_cat=105&ccb=1-7&_nc_sid=f537c7&_nc_ohc=SCo5J30S15sQ7kNvwGOm3qI&_nc_oc=AdohVk9QKa-Te0Nx_YCYN3H_wQi557_C716RSbC29IT2eiHw-Gp8qpFoDCw7zRcBzYQ&_nc_zt=14&_nc_ht=scontent-eze1-1.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQBmn4jDk2JcYwZlZNSIJ0sp_iMpM4M8pfHdB9dY5mJpkQ&oe=6A68C6F4)


#### AWS IAM

This is an example of an AWS IAM policy that allows MFA configuration but forbids other actions if MFA is not present.

![](https://scontent-eze1-1.xx.fbcdn.net/v/t39.8562-6/297883041_801024651261946_2244099280837979731_n.png?_nc_cat=102&ccb=1-7&_nc_sid=f537c7&_nc_ohc=i0w-9UsIUY4Q7kNvwGB3OKi&_nc_oc=AdrJnB1oHT9aCapI59Tmwf9S-t8E_JWgdlHTNfiGnnOHfr8mvl7I_OnHvszYlWxuyTE&_nc_zt=14&_nc_ht=scontent-eze1-1.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQDjj4qXy5lOEA6bSQlmipTc88pX-IYZtMyo6E03jrsgIQ&oe=6A68D0FD)


#### GitHub

An organization has configured GitHub authentication to require MFA for everyone in the organization.

![](https://scontent-eze1-2.xx.fbcdn.net/v/t39.8562-6/297783475_5569491959763684_2694206116726584260_n.png?_nc_cat=108&ccb=1-7&_nc_sid=f537c7&_nc_ohc=DnKJQlyP63oQ7kNvwGONPeN&_nc_oc=Adr7OYJN4dLPC--ppdXb9k3nNua1CiCRvYgeyA2xzcVxEWmHvd1DYD0OZwlA67Pl2W4&_nc_zt=14&_nc_ht=scontent-eze1-2.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQAD1zR_LGCuJD4ld5mk3SOAbnl7wh4O8IX-qAkX_9JI1w&oe=6A68C223)

### Acceptable Alternative Protections

* For any type of remote access that exists in the organization but where MFA is not enforced, you should describe if you are using one or more of these approaches to prevent account takeovers:
  + **Strong password requirements** - E.g., a minimum password complexity, prohibiting dictionary words, prohibiting passwords that are known to have been previously breached
  + **Authentication backoff** - use of a tool that introduces increasingly-long waiting periods in between failed login attempts from the same source
  + **Automatic lockouts** - E.g., a mechanism to automatically block login to an account after 10 failed login attempts

## Have a System for Maintaining User Accounts

**Question**: Do you have a system for maintaining accounts (assigning, revoking, and reviewing access and privileges)?

### Intent

Having good account management hygiene is an important part of preventing unauthorized use of accounts to gain access to Platform Data. In particular, developers must make sure that access to resources or systems is revoked when it’s no longer needed.

* Accounts are the basic unit of management for granting people access to systems, data, and administrative functions
* Accounts are granted permissions that enable specific actions; good practice is to grant only the minimum permissions an account needs – this is called the principle of least privilege
* When a person departs an organization it’s critical that their user accounts are disabled promptly for a couple of reasons:
  + (1) to prevent access by that person (i.e., the former employee), and
  + (2) to reduce the likelihood that an unauthorized person could use the account without being noticed. For example, a malicious actor could use social engineering to cause an IT helpdesk to reset the password for the account. If this account belongs to a current employee, that employee is likely to report their inability to login, whereas if the account is still active but belongs to a departed employee it’s less likely to be noticed.
* With this in mind, organizations must have a systematic way for managing accounts, granting permissions or privileges, and revoking access when it’s no longer needed

### Summary of Requirements

* You must have a tool or process for managing accounts for each of the these tools/systems/apps:
  + Those used to communicate with one another, e.g., Slack or business email
  + Those used to ship software, e.g. code repository and
  + Administer and operate the system (as applicable to processing Platform Data)
* You must regularly review (i.e., not less than once every 12 months) access grants and have a process for revoking access when: (1) it’s no longer required, and (2) no longer being used
* You must also have a process to promptly revoke access to these tools when a person departs the organization
* Meta does not require
  + That any particular tool be used – a developer may use a directory product like Google Cloud identity or Microsoft Azure Active Directory, a cloud product like AWS Identity and Access Management (IAM), or use a spreadsheet that is kept up to date regularly.
  + That there be a single consolidated tool for managing accounts across these various access types.

This requirement applies whether or not you process Platform Data server side.

### Evidence Guide

Follow the instructions in [Preparing Evidence](#evidence-pre) to prepare both policy/procedure and implementation evidence.

* **Policy / procedure** - Provide documented policies and procedure documents that cover the account management practices. We expect this document to contain procedures for creating accounts, granting permissions, minimum password complexity, account lockout policy, MFA policy, account reset procedures, and process for revoking access after a period of inactivity and when people leave the organization (e.g., when an employee resigns or is terminated).
* **Implementation Evidence** - Provide evidence from at least one of the following tools or processes that is in place to manage accounts (or denote as not applicable to the environment): (1) Business email and collaboration tools, (2) Code repository, (3) Cloud/server deployment tools, (4) Cloud/server administrative portal, (5) Cloud/server remote login (e.g., SSH or remote desktop). For the representative distinct tool or process, include evidence that demonstrates that:
  + People that have departed the organization have had their access to these tools revoked (e.g., a reconciliation report comparing user accounts to the authoritative data of current organization members)
  + Access that is not used for some time is revoked (e.g., a report that shows that the last access date of a representative active user account holder is within the past 90 days if the max inactivity period is three months)

### Example Evidence

**Policy / procedure** - A developer has created an Access Lifecycle Management Standard that includes procedures for granting, reviewing, and revoking access.

![](https://scontent-eze1-2.xx.fbcdn.net/v/t39.8562-6/297128500_374312384672234_8418107735522483550_n.png?_nc_cat=100&ccb=1-7&_nc_sid=f537c7&_nc_ohc=LDd9hZD3mu0Q7kNvwG1a01G&_nc_oc=AdprOSDr_Gu6nJiEDLOzFPh1Cgq7JUcTR3f1xhG1qEZWVu-AdcwBWSzY4iuDBvCKiRo&_nc_zt=14&_nc_ht=scontent-eze1-2.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQCLiNd5le-R1gMDX_a4BrE_f8_b24aHBlmjaDzs61Suuw&oe=6A68C1AE)

#### Implementation Example - Access Is Revoked for Departed Personnel

A developer uses Workday as the authoritative source for Human Resources (HR) data, including current employment status. This developer uses Google Cloud Identity as their Identity Provider (IdP) for managing user accounts and granting access to information systems and tools.

A developer submits evidence that access is revoked for departed personnel by submitting a report that shows that a recent (i.e., within the past 12 months) reconciliation report has been run showing that no active user accounts exist in Google Cloud Identity for people who are not active employees according to a Workday report of current employees.

#### Implementation Example - Access is Revoked When No Longer Used

A developer uses Google Cloud Identity as their Identity Provider (IdP) for managing user accounts and granting access to information systems and tools.

A developer submits evidence that access is revoked when it is no longer used (e.g., no logins in the past 6 months) by submitting evidence of their user directory sorted by last sign in to demonstrate that there are no active user accounts where the last sign in was older than this.

![](https://scontent-eze1-2.xx.fbcdn.net/v/t39.8562-6/297496411_563602465450289_3639128198891355145_n.png?_nc_cat=104&ccb=1-7&_nc_sid=f537c7&_nc_ohc=C2uN8pvbxNwQ7kNvwEWZtHy&_nc_oc=AdrpBSM-LCLhGADw0zI4VLfmU3gPzJo7a8cfElXfnTjQvPWW9tF2SHTUwvagQm2rsiE&_nc_zt=14&_nc_ht=scontent-eze1-2.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQCuRjChkHHFe4_o7ye-9hhAKmtwrNEJwgth8uojXkZz3Q&oe=6A68CE72)

#### Implementation Example - GitHub (Code Repository)

A developer uses a Single Sign On (SSO) tool for identity management and granting access to information systems and tools. The developer has configured GitHub to require SSO authentication.

![](https://scontent-eze1-1.xx.fbcdn.net/v/t39.8562-6/297814754_645982476949673_6129938646580617840_n.png?_nc_cat=106&ccb=1-7&_nc_sid=f537c7&_nc_ohc=LBIdWtPt6qwQ7kNvwEMD5_b&_nc_oc=AdpJsva1I1jBloTCnzNSk80tivXBaeDiF-6HDHEjF7XPpp9wuFPFE5gRZHQIdlWsvX4&_nc_zt=14&_nc_ht=scontent-eze1-1.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQBv79_YrGnuoRrwio7ViqF3npOF_Bh1nxSU0n-MYQatsg&oe=6A68A364)

## Keep Software Up to Date

**Question**: Do you have a system for keeping system code and environments updated, including servers, virtual machines, distributions, libraries, packages, and anti-virus software?

### Intent

Software components are routinely updated or patched to resolve security vulnerabilities, and eventually these components will reach their end of life when they are no longer supported. Developers who package or rely on these components must keep up to date to avoid running software with known vulnerabilities.

* App developers rely on a variety of 3rd party software to run apps/systems that process Platform Data
* For example, a developer will rely on some or all of these:
  + **Libraries, SDKs, Packages** - developers package these with their own custom code to build an app
  + **Virtual Machine images, app containers, and operating systems** - an app runs inside one or more of these containers, which provide services like virtualization and access to networks and storage
  + **Browsers, operating systems, and other applications used by employees / contributors** - software that runs on the mobile devices and laptop computers that a developer uses to build and run their system
* Security vulnerabilities are routinely found in these components, leading to patches being released
* Vulnerabilities fixed by patches are then disclosed in public databases with a severity rating (low, medium, high, or critical)
* Therefore, developers using Meta’s platform must have a systematic way to manage patches by
  + Identifying patches that are relevant to their app/system
  + Prioritizing the urgency based on exposure, and
  + Applying patches as an ongoing business activity

### Summary of Requirements

For the following software components, as applicable, you must have a defined and repeatable way of identifying available patches that resolve security vulnerabilities, prioritizing based on risk, and applying patches as an ongoing activity:

1. Libraries, SDKs, packages, app containers, and operating systems used in a cloud or server environment
2. Libraries, SDKs, packages used on client devices, e.g., within mobile apps
3. Operating systems and applications used by members to build and operate the app/system, e.g., operating systems and browsers running on employee laptops

Meta does not require the use of any particular tool for these activities. It’s common that an organization would use different approaches for keeping different types of software up to date (e.g., libraries that are packaged with the app vs operating system updates for employee laptops).

This requirement applies irrespective of the hosting approach (e.g., BaaS, PaaS, IaaS, self hosted, or hybrid), although the set of components that you are responsible for keeping up to date will vary


The diagram below illustrates where patching may be required for various architecture types.

![](https://scontent-eze1-2.xx.fbcdn.net/v/t39.8562-6/297629969_2014913745374849_5849379743279409215_n.png?_nc_cat=104&ccb=1-7&_nc_sid=f537c7&_nc_ohc=iNDpQFvkkXMQ7kNvwG6WdcQ&_nc_oc=AdoJHYTNyOXyytK3J38J2Jg9Yms9XGhg4diA-qg8_iBWpSnihKRKsGkznNuBjNlfVog&_nc_zt=14&_nc_ht=scontent-eze1-2.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQCNVIx-D3ogWjDJnYFQvsMA1Ee5yDwx35Agzh8Fp1bMXA&oe=6A68C380)

### Evidence Guide

If you are asked to submit evidence for this protection, follow the instructions in [Preparing Evidence](#evidence-pre) to prepare both policy/procedure and implementation evidence.

Start by identifying the in-scope types of software in the environment, e.g., Libraries, SDKs, Packages, Virtual Machine images, app containers, and operating systems, Browsers, operating systems, and other applications used by the employees / contributors.

You may have one or more tools that you use for the following activities:

* **Inventory** - document via a screenshot or document that a tool or process that, ultimately, represents a list of in-scope libraries, packages, SDKs, containers, app servers and operating systems that need to be patched. There needs to be inventories for a representative of the software types (e.g., cloud app(s), client app(s), employee devices).
* **Identifying available software patches** - a tool or process must exist for identifying security patches that exist that are relevant to the inventory.
* **Prioritizing** - there needs to be a tool or process (e.g., Jira tickets, GitHub issues, tracking spreadsheet) by which relevant patches are assigned a priority
  + Patching
  + Document via a screenshot or document that demonstrates that, after relevant patches have been identified and prioritized, that they are then rolled out into the various destinations.
* Include policies around time to resolve and use of End of Life (EOL) software.

### Example Evidence

Snyk for a NodeJS app - A developer uses the [Synk](https://l.facebook.com/l.php?u=https%3A%2F%2Fsnyk.io%2F&h=AUBS07LfjdfM7E5ceYlK5xezYS9J1ngksEmVPh85KMf4vArXXVCI837n1e982nkRc6tmMBkoaswRfyOu-cNOj4stMD5MOZGfX4aeXwAoNNFCW9Ro_Xs6Jd96Ha34Tb7_-a42pQd8oWHLElfS) Command Line Interface (CLI) to identify packaged third-party dependencies that have known security vulnerabilities and prioritize based on the severity of those vulnerabilities.

![](https://scontent-eze1-1.xx.fbcdn.net/v/t39.8562-6/297835296_1094229678188461_6918402332375376898_n.png?_nc_cat=111&ccb=1-7&_nc_sid=f537c7&_nc_ohc=aytybC9NpA8Q7kNvwFSEQWY&_nc_oc=AdpY7x6JJ3uceHcbDT6aNPJ2DHqDUrCLECdje4fAFw0H_DieyStRIhSnfiUzwqY6pi0&_nc_zt=14&_nc_ht=scontent-eze1-1.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQCswvnoK0lqHP7AclSziWi9yZF5fGiOldUQ15cS3kDqCA&oe=6A68A6AF)


#### NPM Audit

A developer is using NPM Audit to find vulnerabilities in the dependencies used in a Node application. The example image below shows multiple high severity vulnerabilities that need to be patched.

![](https://scontent-eze1-1.xx.fbcdn.net/v/t39.8562-6/297575700_779907766383876_961844525756760093_n.png?_nc_cat=111&ccb=1-7&_nc_sid=f537c7&_nc_ohc=oIqYQcOaXGsQ7kNvwG5ApFv&_nc_oc=AdqPUA1cH5v4Ek3eGGUnLwwh-Wha9wNItaxKn1Z_rQkknUbVEzMAti-CcmI1PjZDaZM&_nc_zt=14&_nc_ht=scontent-eze1-1.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQCK51vXAyLSOjohSTV7b7eqcticobmH_AKq0eJhhK44-A&oe=6A68A407)


#### Trivy

A developer uses [Trivy to find vulnerabilities in a machine image](https://l.facebook.com/l.php?u=https%3A%2F%2Faquasecurity.github.io%2Ftrivy%2Fv0.27.1%2F&h=AUCljjYxGbPRfoKo4CehCvtMH6QPEwMhSa3Bl3D_xebaZomgajSI_NroSSqw76skRaZ_ON895CUElYECYGt-ZyeXUPmcep1NlM7yKdjH9tboS2sIClRZzzy9jZr-xsowpHb2nC7EjFy3TLcj). The example image below shows high severity vulnerabilities in libraries included in this image that need to be patched.

![](https://scontent-eze1-2.xx.fbcdn.net/v/t39.8562-6/297757255_553927283185317_231244186864047383_n.png?_nc_cat=108&ccb=1-7&_nc_sid=f537c7&_nc_ohc=Q1W4-txMF1IQ7kNvwG-jfJM&_nc_oc=Ado4kOnctnpI7INDDm-Cqp-PNdpd8ofyxpbimWDXdqfc914ZkAn5wBvGZB2Zsx6qZBE&_nc_zt=14&_nc_ht=scontent-eze1-2.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQDLxEKrErKA4oAM_wrBwURBk8zXyG9pZ4NUW-fEDWezXg&oe=6A68A111)


#### Windows Server Update Services (WSUS)

A developer uses [Windows Server Update Services (WSUS)](https://l.facebook.com/l.php?u=https%3A%2F%2Fdocs.microsoft.com%2Fen-us%2Fwindows%2Fdeployment%2Fupdate%2Fwaas-manage-updates-wsus&h=AUD2ilYikZ6uanqutIBApfNLKMc-tgqqfN0Y55-NrO9gqNVYLRNB2P9cj6e2pjOFBPLN2nl08k4D34wdq6MB0-JB0rpcgohNv_W_xY2cIwnwR5ENfKBjsxGqtZsVsh8L5srYZp27B-MLVAz4) to manage their fleet of servers and PCs / laptops. The example image below shows an admin view of the WSUS tool, which allows for reviewing, approving, and deploying Windows updates.

![](https://scontent-eze1-2.xx.fbcdn.net/v/t39.8562-6/297526159_409246807975687_7399948513401394575_n.png?_nc_cat=101&ccb=1-7&_nc_sid=f537c7&_nc_ohc=DRzLbWCJhr8Q7kNvwH4rmO4&_nc_oc=AdrzxiAYUw2DnM5zKgxLC_9xxMHYAzQo9NtCZ6Hy1uKG2HKZHphr_jcgRJKJWUOUzDI&_nc_zt=14&_nc_ht=scontent-eze1-2.xx&_nc_gid=lyO48fX1Sc_N18sXPl5kaw&_nc_ss=7b20f&oh=00_AQB1Uxeg2FS-60oL-4Dsgqxsl8RnDAKyzukCmcbqqbDMnQ&oe=6A689EC1)

## Have a System in Place for Logging Access to Platform Data and Tracing where Platform Data was Sent and Stored

### Intent

Without reliable log files it can be difficult to impossible for a developer to detect unauthorized access to Platform Data.

* Audit logs allow an organization to record the fact that an event occurred, e.g. that a particular user executed a query against database tables containing Platform Data
* These logs can then support processes like triggering automated alerts based on suspicious activity or forensic analysis after a security incident has been identified

### Summary of Requirements

If you process Platform Data server side, then within that environment:

* You should maintain audit logs that record key events (e.g., access to Platform Data, use of accounts with elevated permissions, changes to the audit log configuration)
* Audit logs should be consolidated into a central repository and protected against alteration or deletion

### Evidence Guide

If you’re asked to upload evidence, it should demonstrate that:

* You have a current understanding of how Platform Data is stored, accessed, and transferred, for example via a current data flow diagram that shows an overall view of the system, designates services that store Platform Data, and shows points of ingress and egress, including expected transfers to any 4th party services
* You have implemented tamper resistant audit logs
* Events related to the access of platform data are captured in the logs

## Monitor Transfers of Platform Data and Key Points where Platform Data can Leave the System (e.g., Third Parties, Public Endpoints)

### Intent

Understanding how Platform Data is expected to be processed and then monitoring actual processing is an important way for an organization to make sure that Platform Data is only used for intended purposes

* A developer needs to keep a current understanding of how Platform Data is stored, transmitted via networks, and written to backups (which may be replicated elsewhere)
* For example, monitoring could identify situations where Platform Data is being transmitted in an unexpected way or if it is being transmitted over a network without suitable encryption in transit so that you can take action

### Summary of Requirements

If you process Platform Data server side, then within that server environment, you should:

* Maintain an accurate data-flow diagram that shows where Platform Data is stored, processed, and transmitted across networks
* Configure monitoring (e.g., audit logs with an automated monitoring product) for transfers of Platform Data outside of the system
* Configure, if possible, the monitoring system to raise alerts that are reviewed promptly in the case of unexpected transfers of Platform Data (also see the below requirement - *Have an automated system for monitoring logs and other security events, and to generate alerts for abnormal or security-related events*)

### Evidence Guide

If you are asked to submit evidence for this protection, follow the instructions in [Preparing Evidence](#evidence-pre) to prepare both policy/procedure and implementation evidence.

You should provide evidence that:

* You have a current understanding of how Platform Data is stored, accessed, and transferred, for example via a current data flow diagram that shows an overall view of the system, designates services that store Platform Data, and shows points of ingress and egress, including expected transfers to any 4th party services
* Tamper resistant audit logs have been implemented
* Events related to transfers of Platform Data are captured in the logs; events should include the time, the identity of the user or app taking the action, and the source and destination

## Have an Automated System for Monitoring Logs and Other Security Events, and to Generate Alerts for Abnormal or Security-Related Events

### Intent

It’s unrealistic to rely on humans to review and identify unexpected behavior in a modern internet-accessible system. Instead, tools exist that are able to ingest log files and other signals to raise alarms that need further investigation by people.

### Summary of Requirements

If you process Platform Data server side, then within that server environment, you should:

* Have a tool that is capable of ingesting log files and other events, establishing rules that should raise alarms if tripped, and a mechanism to route alarms to people (e.g., a security investigator who’s on call)
* Ingest relevant signals into the tool (e.g., web access logs, authentication attempts, actions taken by users with elevated privileges)
* Over time, tune and refine the rules to balance signal to noise (e.g., by avoiding too many false alarms but also not ignoring events that warrant investigation)

### Evidence Guide

A developer would commonly adopt a Security Information and Event Management (SIEM) tool for this purpose, for example:

* McAfee Enterprise Security Manager
* SolarWinds Security Event Manager
* Splunk Enterprise Security
* Sumo Logic

You should provide evidence that relevant signal sources are being routed into their tool of choice, that triggers or alarms have been configured, evidence that alarms are routed to personnel who are responsible for following up, and finally that there is a process by which alarms are tuned periodically (e.g., via monthly review and update cycles).

## Glossary

### A

**3rd party** - in risk management terminology, 3rd party refers to developers on Meta’s platform (1st party is Meta itself; 2nd party is people that use Meta’s products)

**4th party** - in risk management terminology, 4th party refers to the firms that developers rely on to provide them services that enable their business (1st party is Meta, 2nd party is Meta’s users, and 3rd party is developers on Meta’s platform)

**Access token** - a credential, like a password, that allows software to call an API to take some action (e.g., read data from a user’s profile).

**Amazon Web Services (AWS)** - Amazon’s suite of cloud computing services

**App scoped ID (ASID)** - a unique identifier that Meta generates when a person chooses to use an app. ASIDs help improve privacy for users by making it more difficult for data sets to correlate users across apps, since a single user using two apps will have different ASIDs in each app.

**App secret** - a shared secret that Meta makes available to developers via the app dashboard. Possession of the app secret authorizes software to take some actions via the Graph API, so developers need to take care that unauthorized parties are not able to get access to the app secret.

**App compromise** - if a malicious actor is able to gain unauthorized access to an organization’s internal network via a misconfiguration or vulnerability in their app (e.g., a software vulnerability in a webapp) it’s called app compromise. A defense against app compromise is to pen test the app. See also *network compromise*.

**Application container** - a container packages up software code and related dependencies so that the app will run on different types of servers (e.g., servers running different operating systems like Linux or Windows Server). A developer will create a container image that packages their app. An application container engine or runtime hosts (runs) the container image.

**Application encryption** - a method of protecting data where the application software itself does the encryption and decryption operations. In contrast, Transport Layer Security (TLS) seamlessly encrypts data in transit when an application establishes a secure connection to a remote server (e.g., using HTTPS) and cloud providers offer services to transparently encrypt data at rest.

**Application Programming Interface (API)** - allows two computers to talk to each other over a network, for example a mobile app fetching today’s weather for a certain location from a centralized weather forecasting system

**Appsecret proof** - an additional layer of security for API calls to Meta whereby a developer generates a parameter (the appsecret proof) that demonstrates that they possess the app secret. The appsecret proof is the product of a hashing function (also called a one-way function) based on the app secret and access token. Configuring an app to require appsecret proofs during Graph API invocations reduces the potential harm from a breach of user access tokens, since those access tokens cannot be used without the additional appsecret proof parameter.

### B

**Backend as a Service (BaaS)** - a style of cloud computing that provides a suite of server-side capabilities for an app developer so that the developer can focus on building the frontend (i.e., the part of an app that users interact with). BaaS solutions are similar to PaaS and, in addition, add services like user authentication and mobile push notifications. For example, these are some popular BaaS products: AWS Amplify, Azure Mobile Apps, Firebase, and MongoDB Switch.

### C

**Cipher text** - a synonym for encrypted data, cipher text is the name given to data that has been made unreadable via some encryption algorithm. The opposite of cipher text is plain text.

**Client side** - people typically interact with internet-accessible services by opening a website in a browser or by running a mobile app on a phone or tablet. The browser or mobile apps are referred to as local clients or client side. Clients make requests from remote computers (servers) via the internet.

**Cloud computing** - refers to a style of managing server computers, networks, and storage so that an organization doesn’t need to worry about the physical environment (i.e., a data center full of server racks and network cables). Instead, the organization can provision these assets on demand and pay for the services that they consume.

**Cloud configuration** - the set of cloud computing options that an organization has set in relation to their use of a cloud provider running some software. Examples of cloud configuration include what sorts of network connections are allowed or blocked, where log files are written and how long they are kept, and the set of users who are authorized to make changes to the cloud configuration.

**Compensating controls** - a security control that differs from some baseline set of requirements but is intended to deliver comparable protection against a risk.

### D

**Database** - software that allows arbitrary data to be stored, read, updated, and deleted. Databases can run on clients and on servers. Organizations that integrate with the Meta platform will commonly store data they fetch from the Graph API in a database that runs server side.

**Decryption** - process by which encrypted data is transformed back into its original format. In other words, decryption changes cipher text into plain text.

### E

**Encryption** - process by which data is transformed into a format that is unusable to anyone that cannot decrypt it. In other words, encryption changes plain text into cipher text.

**Encryption at rest** - data that has been protected with encryption when written to persistent storage (e.g., a disk drive). Encryption at rest provides an additional layer of protection against unauthorized access since an actor that’s able to read the raw files on the storage device will see cipher text and will not be able to decrypt it unless they are also able to gain access to the decryption key.

**Encryption in transit** - data that has been protected with encryption when transmitted across a network. Encryption in transmit provides protection against eavesdropping along the network path since an actor that’s able to read the network packets will see cipher text and will not be able to decrypt it unless they are also able to gain access to the decryption key.

**End of Life (EOL) software** - when an organization chooses to stop support (e.g., create patches to resolve security vulnerabilities) for a software product that software is considered EOL. Since this software is no longer maintained, it’s very risky to run any EOL software.

### G

**Google Cloud Platform (GCP)** - Google’s suite of cloud computing services

**Graph API** - the primary way for apps to read and write to the Meta social graph. All Meta SDKs and products interact with the Graph API in some way.

### H

**Hashing function** - a cryptographic function that takes any data as input and outputs a short code that cannot be reversed into the original input. In cryptography, hashing functions are used to protect data like passwords – instead of storing a user’s password in plaintext that could be stolen, passwords are first transformed with a hash function and then stored. Later, to confirm that a user has input the correct password, the system will use the same hash function to transform the input and compare the resulting hash against the stored value. Also called a *one-way function* since the output hash cannot be reversed into the original input.

**Hosted environment** - refers to a set of remote servers, networks, and storage devices that an organization is running in their own data center or within a data center co-located (or colo) with other customers. This arrangement is relatively uncommon in the modern era since cloud computing has become more popular.

### I

**Identity Provider (IdP)** - a cloud service used to centralize management of digital identities and authenticate users. Organizations that use an IdP typically configure cloud apps to rely on the IdP for user authentication. The organization can then manage users by creating, granting access to selected apps, and disabling user accounts centrally within the IdP instead of having to do this repeatedly in each cloud app.

**Identity and Access Management (IAM)** - refers to the category of tools and processes that are used to manage accounts and grant access to systems.

**Infrastructure as a Service (IaaS)** - a cloud computing approach that lets customers configure computing, storage, and networking services without having responsibility for the physical assets themselves (e.g., managing a data center full of servers, network devices, and storage arrays). Compared to Paas, IaaS gives an organization more control over the configuration of their cloud assets but at the cost of more complexity to manage those assets. For example, these are some popular IaaS products: AWS EC2, Microsoft Azure IaaS, and Google Compute Engine.

### L

**Library** - pre-existing software building blocks, typically from an external company or developer, that’s used to handle certain tasks within another developer’s app or system. Libraries simplify development of an app since a developer doesn’t have to reinvent the wheel when a library already exists for a given function. However, libraries can contain security vulnerabilities – or can themselves include additional libraries that do – so developers who use libraries as part of their app need to know what libraries are in use and keep them up to date over time.

### M

**Mobile client or mobile app** - an app that a person installs onto a phone or table from a mobile app store (e.g., iOS App Store or Google Play Store). It’s common for mobile clients to communicate over the internet with an organization’s REST API and may also communicate with other parties (e.g., to the Graph API via the Facebook SDK for Android).

**Multi-Factor Authentication (MFA)** - an authentication approach that requires more than one factor to gain access to an app or system. MFA, in contrast to single factor authentication that relies on just a password to authenticate a user, will typically require a password plus one or more of these: a code sent via email or SMS, a code from an authenticator app, a biometric scan, or a security key. MFA protects against account takeovers by making it more difficult for unauthorized actors to force their way into an account, e.g., by repeatedly attempting to login to an account by using a known email address and common passwords until successful.

### N

**Native software** - apps that are downloaded and installed onto laptops or mobile devices are referred to as native software (e.g., the Facebook app for iOS). In contrast, an app that runs within a browser is referred to as a webapp (e.g., opening Facebook using the Chrome browser).

**Network compromise** - if a malicious actor is able to gain unauthorized access to an organization’s internal network via a misconfiguration or vulnerability in the network itself it’s called a network compromise. A defense against network compromise is to run a network scan to identify misconfigurations and vulnerabilities in the internet-facing network. See also application compromise.

**Network scan** - a risk management process that uses software to: (1) identify active servers on a network that will respond to remote communications, and then (2) see if any of those servers are running old versions of software that is known to be vulnerable to one or more security exploits. An organization may use network scanning periodically to make sure that there are no unexpected open ports on their network perimeter, for example.

**Node Package Manager (NPM)** - a tool used by JavaScript developers to speed up development by allowing pre-built packages to be included in a developer’s app or system. NPM includes features to audit the set of packages that are in use by an app and to identify packages that have known security vulnerabilities.

### O

**Object storage buckets** - a type of persistent storage in the cloud that makes it simple for organizations to store files into persistent storage, including files that are very large, without having to worry about scaling physical assets like storage arrays or how to back these files up to ensure they aren’t lost in the case of a disaster like a fire or flood.

**Operating System** - the software running on a computer or mobile device that allows applications to run and use that computer’s processor, memory, storage, and network resources. For example, Microsoft’s Windows, Apple’s macOS or iOS, and Linux.

**Organization member** - someone with a role and responsibilities within an organization, for example an employee, a contractor, a contingent worker, an intern, or a volunteer.

**Organizational device** - a computer or mobile device used by an organization member in the context of doing work for the organization.

### P

**Platform Term 6.a.i** - Refers to Meta’s Platform Terms section (6) heading (a) paragraph (i), which describes platform developers’ obligations related to data security.

**Package** - synonym for library

**Patch** - software updates that resolve security vulnerabilities, fix bugs, or add new functionality. All sorts of software gets patched, including Operating Systems, containers, libraries, and SDKs.

**Penetration test** - a simulated attack against an app or system where the tester attempts to find vulnerabilities in the code or configuration that could be exploited by an unauthorized actor. Pen testers will use similar tools to cyber criminals to conduct reconnaissance, scan for potential weaknesses, and test vulnerabilities that could be used to gain unauthorized access. At the conclusion of a pen test, the tester will create a report that describes the findings along with the severity of each and the organization that maintains the software is responsible for crafting fixes to resolve the vulnerabilities.

**Plain text** - a synonym for unencrypted data, plain text is the name given to data that has not been protected by encryption.

**Platform as a Service (PaaS)** - a cloud computing approach whereby a customer deploys an application into a platform managed by the cloud provider. Compared to IaaS, PaaS is simpler for customers to manage since not only the physical assets (i.e., the servers, storage devices, and network devices) are managed by the cloud host but also the operating system and application container where the customer’s app runs. For example, these are some popular PaaS products: AWS Elastic Beanstalk, Google App Engine, Force.com.

**Port** - when a client makes a connection to a server over the internet the destination address has two parts: (1) an Internet Protocol (IP) address for the server and (2) a port number on that server that a particular application will respond to. Common protocols use reserved ports (e.g., HTTPS uses 443) but a developer can use custom ports for network communications if desired.

### R

**REST API** - a widely adopted style of building web-accessible services where the client and server communicate using the HTTP protocol. A developer on the Meta platform might host a REST API on a subdomain like api.example.com that their mobile app sends and receives Platform Data to/from.

### S

**Secure Shell (SSH)** - a communication scheme that allows administrators to remotely login to servers and run programs on those servers. Referred to as secure since the communications between the client and server are protected against eavesdropping unlike earlier protocols like Telnet. Also called *Secure Socket Shell*.

**Secure Sockets Layer (SSL)** - An obsolete and insecure version of encryption in transit. The modern secure version is called Transport Layer Security (TLS).

**Server** - a computer that provides services remotely over a network. Browsers and mobile apps connect to servers over the internet.

**Serverless computing** - a style of cloud computing where the cloud host manages the physical infrastructure, the server operating system, and the container. A developer is only responsible for custom code and associated libraries along with the cloud configuration.

**Server side** - data or computation on the other side of a network connection (i.e., on a server) is referred to as server side. In contrast, data or computation on a local device like a laptop or mobile device is referred to as client side.

**Single Sign On (SSO)** - an arrangement where apps rely on a centralized user directory (i.e., an IdP) to authenticate users. In addition to centralizing user account and app access administration for the organization, users benefit by having a single set of credentials instead of requiring users to maintain different credentials (e.g., username and password) for each different app.

**Software Development Kit (SDK)** - a building block of code that a developer can use to simplify the development process for a given need. For example, Meta creates and maintains SDKs that simplify working with the Graph API for iOS and Android developers. Similar to a library, developers that use SDKs in their apps need to keep them up to date over time.

**Software as a Service (SaaS)** - allows customers to use cloud-based apps via the internet. Unlike PaaS or IaaS, a customer of a SaaS app does not deploy custom code nor have responsibility for configuring, upgrading, or patching the SaaS app as all of these are the responsibility of the SaaS software vendor. For example, these are some popular SaaS products: Dopbox, MailChip, Salesforce, Slack.

**Static analysis** - see Static Application Security Testing

**Static Application Security Testing (SAST)** - an approach for finding vulnerabilities in software by running a specialized tool against the source code. A SAST tool will identify potential vulnerabilities, such as those listed in the OWASP Top 10 project, and then the developer is responsible for reviewing the findings, distinguishing true positives from false positives, and fixing vulnerabilities in the software. SAST can be useful because it can allow developers to find vulnerabilities before they are deployed into production, but unlike a penetration test a SAST tool will not be able to find vulnerabilities related to the production configuration of the app.

### T

**Transparent data encryption** - a type of encryption at rest that typically applies to database storage (i.e., the database contents themselves and its log files). In this arrangement, the database software manages the encryption keys and transparently handles the encryption operations (upon writes) and decryption operations (upon reads).

**Transport Layer Security (TLS)** - an encryption in transit scheme that uses encryption to protect data transmitted over networks from eavesdroppers along the network path. TLS is the modern secure version of the obsolete earlier technology called SSL.

**Two-Factor Authentication (2Fac)** - a synonym for Multi-Factor Authentication.

### V

**Vault** - a secret management system for sensitive data like encryption keys, access tokens, and other credentials. A vault allows tight control over who is able to access the secrets it contains and offers additional services like keeping audit logs.

**Virtual Machine (VM)** - very similar to an Application Container – a VM runs in a host called a hypervisor whereas an Application Container runs in a container engine. The main difference is that a VM image contains an Operating System whereas an Application Container will not. Both VMs and Application Containers contain application(s) and dependencies like libraries.

**Virtual Private Cloud (VPC)** - term used by AWS to refer to a set of cloud resources that resembles a traditional network in a data center in the pre-cloud era.

**Vulnerability** - a flaw in a system or app that could be exploited, e.g., to read data that the actor otherwise would not be entitled to read

**Vulnerability Disclosure Program (VDP)** - an approach whereby organizations solicit security vulnerability reports from researchers (sometimes called ethical hackers) so that the vulnerabilities can be discovered and fixed before malicious actors exploit them. An effective VDP requires a set of researchers who are actively looking for vulnerabilities, analysts within the organization to review and triage incoming disclosures, and engineers who are knowledgeable about cybersecurity that are able to create and deploy fixes for vulnerabilities.

**Vulnerability scan** - an approach that uses software to look for vulnerabilities in servers, networks, and apps. Compared to a penetration test, a vulnerability scan is cheaper to run and hence can be run repeatedly (e.g., monthly or quarterly) but it’s typical that a pen test will find vulnerabilities that a vulnerability scan misses because skilled penetration testers bring analytical skills and instincts that are hard to replicate with strictly automated approaches. See also network scan.

### W

**Webapp** - Webapps are programs that run inside browsers and are comprised of resources like HTML documents, JavaScript code, videos and other media, and CSS for styling. In contrast to a mobile app that a person installs onto a mobile phone from an app store, people simply fetch a webapp from a remote server using their browser (e.g., www.facebook.com) without the need for an installation step.
