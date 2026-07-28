# Data Protection Security Requirements



**Warning:** Here you can find security requirements to help with the data protection questions in the data acesss renewal assessment.

These data security requirements are intended to provide helpful information and assist you in completing the data protection section of Meta’s data access renewal assessment.  For any given question, please note there may be more than one way to demonstrate that you meet our requirements.  Only a member of Meta’s review team can make a final determination on whether the evidence provided meets the requirements of the assessment. In addition to using this guide, we recommend consulting with your Chief Information Officer, the person with an equivalent role within your organization, or a qualified cybersecurity firm when preparing your responses to ensure your responses are complete and accurate.

A subset of the data access renewal assessment is focused on Platform Term 6, which outlines data security requirements. We recommend you utilize this document to understand the expectations, requirements, and related evidence with respect to data security use and processing as defined in Meta Platform Terms.

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
2. How you fetch Platform Data from Meta&#039;s APIs, including PII like name, email address, gender, birthdate, and other user data.
3. How you use, store, and transmit this data.
4. Any 4th parties to which Platform Data is sent.

## Preparing Evidence ##  &#123;#Preparing-evidence&#125;

When submitting evidence to support your data security measures, please refer to the Evidence Guide provided in this document for examples of acceptable evidence. We accept common document file types, screenshots, and screen recordings. Ensure that files are not password protected and do not exceed 2 GB each. Accepted file types include .xls, .xlsx, .csv, .doc, .docx, .pdf, .txt, .jpeg, .jpg, .png, .ppt, .pptx, .mov, .mp4, .zip, and .zipx.

**Redacting Sensitive Data**

Before submission, remove any sensitive data from your evidence. This includes, but is not limited to:

- Health and financial data
- IP addresses, passwords, credentials, and access tokens
- Encryption keys and physical addresses
- Personally Identifying Information (PII) such as names, email addresses, user IDs, birthdates, and location data
- Any data potentially identifying individuals indirectly, such as cultural, social, or political identities
- Details of vulnerabilities, especially those involving children under the age of 13

**Types of Evidence Required**

Meta requires two types of documentation for each data security question:

1. **[Policy or Procedure Evidence](https://developers.facebook.com/docs/resp-plat-initiatives/data-protection-assessment/data-security/version2.5#policy-procedure-evidence)**: This should be a document detailing your data security policies or procedures that align with Meta&#039;s standards. It can be an excerpt from internal policies, part of an internal wiki, or a newly created document.
2. **[Implementation Evidence](https://developers.facebook.com/docs/resp-plat-initiatives/data-protection-assessment/data-security/version2.5#implementation-evidence)**: This should demonstrate the practical application of your policies or procedures, such as tool configurations or screenshots showing the implemented measures.

**Guidelines for Evidence Submission**

- **Policy or Procedure Evidence**: Must clearly articulate how your measures meet or exceed Meta&#039;s requirements. Only include relevant sections necessary for the review.
- **Implementation Evidence**: Provide screenshots or screen recordings that accurately represent how you have applied the security measures. Ensure the evidence is as detailed as the examples provided by Meta.

## Backend Storage, Data Stored, and Hosting Questions

### All questions
backendstorage-8, datastored-8.a, hosting-8.b, hosting-8.b.i, certifications-8.c

### Summary
In order to perform our reviews accurately, we need to first understand how Platform Data is processed and stored by your system or application.

This section asks if you store Platform Data in a backend environment, and if so:

- Which specific Platform Data attributes

- What backend hosting approach(es) are used

### Changes from prior version

- You will now be asked if your organization holds certain information security certifications.

### Additional guidance
“Store” refers to writing Meta Platform Data into any environment that retains data after the power is shut off (e.g., log files, object or relational databases, or disks).

### External resources
Not familiar with security in server or backend environments? Review these resources.

* [CSA: Cloud Security Alliance ](https://cloudsecurityalliance.org/)
* [AWS: Security best practices for Amazon S3 ](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-best-practices.html)
* [Azure: Azure security baseline for Storage](https://learn.microsoft.com/en-us/security/benchmark/azure/baselines/storage-security-baseline)
* [GCP: Google Cloud security best practices ](https://cloud.google.com/security/best-practices)
* [Heroku: Heroku Security  ](https://www.heroku.com/policy/security)
* [Alibaba Cloud: Cloud Security on Alibaba Cloud ](https://www.alibabacloud.com/solutions/security)
* [Tencent Cloud: TencentDB for MySQL Security White Papers ](https://www.tencentcloud.com/document/product/236/35293)
* Oracle Infrastructure:
    * [Oracle Infrastructure and Platform Cloud Services Security](https://www.oracle.com/assets/oracle-inf-cloud-security-wp-3840537.pdf)
    * [Oracle Cloud Infrastructure Security Guide ](https://docs.oracle.com/en-us/iaas/Content/Security/Concepts/security_guide.htm)
* [Digital Ocean: Digital Ocean Data Security ](https://www.digitalocean.com/security/shared-responsibility-model-droplets)
* [Cisco: What Is Data Center Security](https://www.cisco.com/c/en/us/solutions/security/secure-data-center-solution/what-is-data-center-security.html)

### Evidence examples
Developers are not required to provide evidence in response to this question.

## Backend Encryption and Hosting Security Questions

### All questions
backendencryption1-9a, backendencryption2-9.a, backendencryption-9.b.i, backendencryption-9.b.ii, hostingsecurity-9.c.i, hostingsecurity-9.d.i

### Summary

Encryption at rest protects Platform Data by making the data indecipherable without a separate decryption key. This provides an additional layer of protection against unauthorized read access in cloud or server environments where Platform Data tends to be concentrated.

You must encrypt all Platform Data stored within your backend environments. You may be asked to provide policy/procedure documentation and screenshot proof to demonstrate you have implemented this control.

This section asks if Platform Data stored in your backend environment is protected with encryption at rest or another acceptable approach to reduce the risk of data loss.

### Additional guidance

**Backendencryption-9.b.i, backendencryption-9.b.ii Requirements**

You must encrypt all Platform Data stored within your backend environments. You may be asked to provide policy/procedure documentation and screenshot proof to demonstrate you have implemented this control.

| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| Backendencryption-9.b.i -  Provide a written explanation that states that all Platform Data stored in your backend environments must be protected with encryption at rest.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;If you categorize and protect data differently according to a set of data sensitivity levels, your explanation should clearly indicate what sensitivity level is assigned to Meta Platform Data received from Meta, and you should upload the relevant policies. | backendencryption-9.b.ii - Provide at least one piece of evidence (e.g., a screen capture of a database instance) that shows how all Platform Data stored in your backend environment is protected with encryption at rest.&lt;br&gt;&lt;br&gt;For example:&lt;br&gt;&lt;br&gt;• A configuration in a dashboard/ console&lt;br&gt;• A graphical user interface (GUI) that shows encryption through code&lt;br&gt;• Encrypted fields (please redact any unencrypted data in the screenshot).&lt;br&gt; |

**Hostingsecurity-9.c.i, hostingsecurity-9.d.i Requirements**

| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| hostingsecurity-9.c.i - Provide a written explanation that states the type of certification you possess.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;Please confirm in writing that your hosting provider’s ISO 27001 or SOC 2 audit had:&lt;br&gt;&lt;br&gt;1. In-scope physical security; and&lt;br&gt;2. Secure media disposal controls.&lt;br&gt;&lt;br&gt;For ISO/IEC 27001:2013 or 2017 standards, these are controls A.8.3, A.11.1, and A.11.2.&lt;br&gt;For SOC 2 standard, these are controls CC6.4 and CC6.5. | hostingsecurity-9.d.i - Provide your hosting provider’s ISO 27001 or SOC 2 Type 2 certificate.&lt;br&gt;&lt;br&gt;• If you are not legally allowed to share the certificate itself, upload a written statement that contains the name of the auditor and the date the certificate was issued.&lt;br&gt;• The certificate is invalid if the SOC 2 Type 2 issuance date is older than 1 year or if the ISO 27001 is older than 3 years compared to the date of your DPA notification.&lt;br&gt; |

### External resources
Not familiar with encryption at rest in a server or backend environment? Review these resources.

* [NIST -  Protection of Data at Rest ](https://csrc.nist.gov/csrc/media/projects/cryptographic-module-validation-program/documents/security-policies/140sp2089.pdf)
* [CIS - Encrypt Data at Rest - Essential Guide to Election Security  ](https://essentialguide.docs.cisecurity.org/en/latest/bp/encrypt_data_at_rest.html)
* [OWASP - Cryptographic Storage - OWASP Cheat Sheet Series](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html)
* [AWS  - Encrypting File Data with Amazon Elastic File System ](https://docs.aws.amazon.com/whitepapers/latest/efs-encrypted-file-systems/encryption-of-data-at-rest.html)
* [GCP - Default encryption at rest \| Documentation \| Google Cloud  ](https://cloud.google.com/docs/security/encryption/default-encryption)
* [Azure - Azure Data Encryption-at-Rest - Azure Security \| Microsoft Learn ](https://learn.microsoft.com/en-us/azure/security/fundamentals/encryption-atrest)

### Evidence examples
[hostingsecurity-9.b.i and 9.b.ii evidence examples](https://developers.facebook.com/docs/resp-plat-initiatives/data-protection-assessment/data-security/version3.1#q319)

## Device Storage Questions

### All questions
devicestorage-10, devicestorage1-10.a, devicestorage2-10.a, devicestorage-10.a.i, devicestorage-10.a.ii,devicestorage-10.a.iii, devicestorage-10.a.iv, devicestorage1-10.b, devicestorage2-10.b, devicestorage1-10.c, devicestorage2-10.c, devicestorage2-10.b, devicestorage-10.ci,  devicestorage-10.c.ii, devicestorage-10.d

### Summary
If your organization allows Platform Data on devices like employee laptops or removable storage (e.g., USB drives), that data is at high risk of unauthorized access if the device is lost or stolen. We require developers to take steps to limit this risk to Platform Data.

If you don’t allow storage of Platform Data on devices, but it is still accessible to members of your organization, we require developers to take steps to limit unauthorized use/storage.

This question asks if you have technical or administrative controls to limit the risk of loss of confidentiality of Platform Data stored on organizational and personal devices.

### Additional guidance
**devicestorage1-10.a, devicestorage2-10.a Requirements**

This requirement applies to all developers that have at least one member that could process  Platform Data on an organizational or personal device such as a work or personal laptop computer.

If you store Platform Data on organizational devices or removable media:

**You must have EITHER technical controls OR administrative controls** relevant to Platform Data stored on organizational devices (e.g., laptops) and removable media.

**Acceptable Technical Controls:**
| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| devicestorage-10.a.i - Provide a written explanation (e.g., a policy or procedure document) that states how you implemented ONE of the following controls:&lt;br&gt;• Full disk encryption for all organizational devices where Platform Data is held, or&lt;br&gt;• Use of Data Loss Prevention software to monitor and log actions related to the stored Platform Data&lt;br&gt; | devicestorage-10.a.ii - Provide at least one piece of evidence (e.g., a tool configuration or screen capture from your application) that shows how you implement technical protections for Platform Data stored on organizational or personal devices.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;If you allow storage of Platform Data on organizational / personal devices, you should provide a screenshot that shows how you:&lt;br&gt;&lt;br&gt;1. Enforce full disk encryption on all organizational devices through a configuration or group policy; OR&lt;br&gt;2. Use Endpoint Data Loss Prevention (DLP) software on all managed devices where Platform Data] is held. Your DLP solution must be configured to log and track Platform Data and Personal Identifiable Information (PII).&lt;br&gt;&lt;br&gt;Please note the control must be enforced at an organizational level through a configuration dashboard, ruleset, etc. A screenshot of the control implemented on a single device will NOT be accepted.&lt;br&gt;&lt;br&gt;Examples of Acceptable Evidence:&lt;br&gt;&lt;br&gt;* A screen capture of a Group Policy that requires BitLocker to be enabled for managed devices.&lt;br&gt;* A screen capture of a DLP management tool that shows PII data monitoring is enabled for all endpoints.&lt;br&gt;* A screen capture of another tool or product that your IT administrators use to enforce the use of technical protections on all organizational devices. |

**Acceptable Administrative Controls:**
| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| devicestorage-10.a.iii - Provide a written explanation (e.g., a policy or procedure document) containing your acceptable use policy.  &lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;Your written explanation must include an acceptable use policy that only allows processing Platform Data if:&lt;br&gt;&lt;br&gt;• There is a clear and actionable business purpose; and&lt;br&gt;• States that the data must be deleted when the business purpose no longer exists.&lt;br&gt; | devicestorage-10.a.iv - Confirm that all people in your organization who may process Platform Data on organizational or personal devices:&lt;br&gt;• Have been informed of the acceptable use policy for this data&lt;br&gt;• Have acknowledged their understanding of this policy&lt;br&gt;• Are informed of this policy as part of their onboarding as new employees&lt;br&gt; |

**Devicestorage1-10.b, devicestorage2-10.b, devicestorage1-10.c, devicestorage2-10.c Requirements**

If you do not store platform data on organizational devices but it is still accessible to members of your organization, we require that you forbid storage of platform data on all organizational devices and removable media:

| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| devicestorage-10.c.i -  Provide a written explanation (e.g., a policy or procedure document) that states that people in your organization must not store Platform Data on organizational devices (laptops, tablets, etc.) and removable media (USB devices, phones, etc.).&lt;br&gt;&lt;br&gt;Please highlight or circle the clause in your policy that relates to this control. If you have data classification and data handling policies to determine controls on Platform Data storage, please indicate how you have classified Platform Data.&lt;br&gt;&lt;br&gt;Data Storage Policy Exclusions:&lt;br&gt;&lt;br&gt;If your policy indicates exclusions or allowable circumstances in which Platform Data can be stored on organizational devices, please change your devicestorage-10 answer to “Yes. One or more people in my organization store Platform Data] on their organizational or personal devices.” | devicestorage-10.c.ii - Confirm that all people in your organization:&lt;br&gt;• Have been informed of the policy prohibiting them from storing Platform Data on organizational or personal devices&lt;br&gt;• Have acknowledged their understanding of this policy&lt;br&gt;• Are informed of this policy as part of their onboarding as new employees&lt;br&gt; |

**devicestorage-10.d Requirements**

If you store Platform Data neither in a backend environment nor on organizational devices and removable media, please provide a data flow diagram and a description of how your app uses Platform Data. The following details should be included:

- Show how your app makes calls to Meta APIs, such as graph.meta.com;

- Label frontend (web or mobile client) and backend (server / cloud) application components that use Platform Data as such; and

- Ensure all persistent storage of Platform Data is clearly shown in the diagram. List the Platform Data attributes (including access tokens, app secret, etc.) that are stored, cached, processed, or transferred

### External resources
Not familiar with encryption at rest on organizational and personal devices? Review these resources.

* [CIS: EI-ISAC Encrypt Data at Rest ](https://essentialguide.docs.cisecurity.org/en/latest/bp/encrypt_data_at_rest.html)
* [OWASP: OWASP Cheat Sheet Series](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html)
* [Apple IOS: FileVault on MAC OS](https://support.apple.com/guide/mac-help/how-does-filevault-work-on-a-mac-flvlt001/mac)
* [Linux: Linux Disk Encryption](https://devconnected.com/how-to-encrypt-file-on-linux/#:~:text=To%20encrypt%20files%20using%20a,that%20you%20want%20to%20encrypt.&amp;text=The%20%E2%80%9Cgpg%E2%80%9D%20command%20will%20create%20a%20file%20with%20a%20%E2%80%9C)
* [MS O365: Set up encryption in Microsoft 365 Enterprise](https://learn.microsoft.com/en-us/purview/set-up-encryption)

### Evidence examples
[devicestorage-10 evidence examples](https://developers.facebook.com/docs/resp-plat-initiatives/data-protection-assessment/data-security/version3.1#310)

## Transit Encryption Questions

### All questions
transitencryption1-11.a, transitencryption1-11.b, transitencryption1-11.d, transitencryption1-11.a.i, transitencryption1-11.a.ii

### Summary
Platform Data transmitted across the internet is accessible to anyone that can observe the network traffic. Therefore it must be protected with encryption to prevent those unauthorized parties from being able to read the data.

* Encryption in transit protects Platform Data when it is transmitted across untrusted networks (e.g., the internet) by making it indecipherable except for the origin and the destination devices
* In other words, parties in the middle of the transmission would not be able to read Platform Data even if they can see the network traffic (this is also called a man-in-the-middle attack)
* TLS is the most prevalent form of encryption in transit because it’s the technology that browsers use to secure communications to websites like banks

This section asks if you always protect Platform Data with encryption in transit when sending it over the Internet.

### Additional guidance
This requirement applies to all developers who transmit Platform Data over the internet for any reason other than requests directly to Meta:

- Platform Data must never be transmitted across untrusted or third party networks in unencrypted format including transmission of platform data to your cloud environment outside of a Virtual Private Cloud (VPC)

- For all web listeners (e.g., internet-facing load balancers) that receive or return Platform Data, you must:

- Enable TLS 1.2 or above

- Disable SSL v2 and SSL v3

- TLS 1.0 and TLS 1.1 may only be used for compatibility with client devices that are not capable of TLS 1.2 or greater

- Meta recommends, but does not require, that encryption in transit be applied to transmissions of Platform Data that are entirely within private networks, e.g., within a Virtual Private Cloud (VPC)

**transitencryption1-11.a Requirements**

| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| transitencryption1-11.a.i - Provide a written explanation (e.g., a policy or procedure document) that states how you enable security protocol TLS 1.2 or greater for data in transit.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;You will need to provide the following information:&lt;br&gt;&lt;br&gt;1. Upload a written explanation (e.g., a policy or procedure document) that states how you enable security protocol TLS 1.2 or greater for data in transit; and&lt;br&gt;2. Highlight or circle where in your policy the following conditions are outlined:&lt;br&gt;* Platform Data is never transmitted without encryption in transit; and&lt;br&gt;* SSL version 2 and SSL version 3 are never used. | transitencryption1-11.a.ii - Provide at least one piece of evidence that shows how you enable security protocol TLS 1.2 or greater for data in transit.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;You will need to provide the following information:&lt;br&gt;&lt;br&gt;1. Evidence from your system or application, such as a tool configuration or screen grab; and&lt;br&gt;2. That evidence shows how you enable TLS 1.2 or greater.&lt;br&gt;&lt;br&gt;For Example:&lt;br&gt;&lt;br&gt;1. Evidence could include a full screen capture of the results of a Qualys SSL report run against one of your web domains;&lt;br&gt;2. Load balancer SSL configuration found in cloud hosting provider settings; or&lt;br&gt;3. Script or code showing TLS 1.2 is enabled. |

The table below summarizes encryption in transit policy for different transmission types:

| Type of Transmission | Encryption in Transit Policy |
| --- | --- |
| To and from end user devices (mobile phones, PCs, tablets, etc.) and the server or cloud infrastructure | * TLS 1.2 or greater must be enabled for compatible devices&lt;br&gt;* TLS 1.0 and 1.1 may be enabled for compatibility with older devices |
| To and from the server or cloud infrastructure and any remote server, cloud infrastructure, or 4th party service | * TLS 1.2 or greater must be enforced |
| To and from components entirely within the private data center, server, or cloud infrastructure | * TLS encryption is recommended but not required for Platform Data transfers that are entirely within a private cloud network |
| To and from Meta and any device, server, or cloud infrastructure | * Out of Scope for Data Protection Assessment - Meta controls the TLS policy for these transfers |

### External resources
Not familiar with encryption in transit? Review these resources.

* [NCSC (UK): UK National Cyber Security Centre - data in transit ](https://www.ncsc.gov.uk/collection/cloud/the-cloud-security-principles/principle-1-data-in-transit-protection)
* [AWS Well Architected: SEC09-BP02 Enforce encryption in transit](https://docs.aws.amazon.com/wellarchitected/latest/framework/sec_protect_data_transit_encrypt.html)
* [LinkedIn Collaborative Articles: What are the best practices for testing and auditing your data encryption in transit and at rest? ](https://www.linkedin.com/advice/0/what-best-practices-testing-auditing-your#how-to-encrypt-data-in-transit)

### Evidence examples
[transitencryption1-11.a evidence examples](https://developers.facebook.com/docs/resp-plat-initiatives/data-protection-assessment/data-security/version3.1#311)

## Testing Questions - Application and Cloud Security Testing

### All questions
testing1-12.a, testing-12.a.i, testing-12.a.ii, testing1-12.b, testing-12.b.i, testing-12.b.ii, testing1-12.c, testing-12.c.i, testing-12.c.ii

### Summary

You must test for vulnerabilities and security issues so that they can be discovered proactively, ideally preventing security incidents before they happen

* Developers write software and operate apps and systems to process Platform Data
* These apps and systems may contain security vulnerabilities that malicious actors can exploit, putting Platform Data at risk
* You must take steps to find and resolve these kinds of vulnerabilities

This section asks about steps you take to test your software and cloud configuration for vulnerabilities and security issues.

### Additional guidance
**testing1-12.a, testing1-12.b Requirements**

This requirement is applicable to all developers.

| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| testing-12.a.i,  testing-12.b.i - Provide a written explanation (e.g., a policy or procedure document) that states how you test the software you use to process Platform Data for vulnerabilities and security issues.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;The following testing procedures should all be included in your written explanation:&lt;br&gt;&lt;br&gt;• Test for security vulnerabilities at least once every 12 months&lt;br&gt;• Have a process to triage the findings based on severity&lt;br&gt;• How you ensure that high severity vulnerabilities, which could lead to unauthorized access to Platform Data, are remediated in a timely manner&lt;br&gt; | testing-12.a.ii, testing-12.b.ii - Provide evidence (e.g., a summary of the outcome of a recent penetration test with a date) that shows how you test the software you use to process Platform Data for vulnerabilities and security issues.&lt;br&gt;&lt;br&gt;Please ensure all uploaded evidence includes a timestamp and aligns with your testing1-12.a or testing1-12.b selection(s).&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;The following details should be included in your evidence:&lt;br&gt;&lt;br&gt;• An explanation of the scope and testing methodology&lt;br&gt;• The date when the testing activity took place&lt;br&gt;(To be acceptable, the date cannot be more than 12 months old from our DPA notification date)&lt;br&gt;• An output of identified vulnerabilities, including severity level (or category) for each finding.  Where applicable, include a summary of any unremediated Critical or High vulnerabilities, and whether any of those vulnerabilities present a risk of unauthorized access to Platform Data.&lt;br&gt;&lt;br&gt;&lt;br&gt;[Remove or redact sensitive information](https://developers.facebook.com/docs/development/maintaining-data-access/data-protection-assessment/data-security#redact-evidence) such as detailed vulnerability reproduction steps from the evidence before submitting. |

**Vulnerability Disclosure Program (VDP)**

If you are operating a functioning Vulnerability Disclosure Program (VDP), e.g., using the [BugCrowd](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.bugcrowd.com%2Fglossary%2Fvulnerability-disclosure-program-vdp%2F%3Ffbclid%3DIwAR1kjHH1T9UiElOPLlgUM2DJKlW8RQfCyVVCEXm_oGKOblW3F39OrqDewXw&amp;h=AT1w52ZKkmbE5C_9DjvT4F3aEnVtXibjoaoHR-ZQKemPZvvjP5yJe6SVBJm5u82HIpGxm1iBytcbGithIJTY3TKaZHWxbmABG6B4O_RlvlCw_i9rTVL-b_iABSfgiLkDumFHeVE1pE9kcYK1U1inDQ),  [HackerOne](https://l.facebook.com/l.php?u=https%3A%2F%2Fwww.hackerone.com%2Fproduct%2Fresponse-vulnerability-disclosure-program%3Ffbclid%3DIwAR34jZtGcKVi3CTwRzUdSpjYovOu04Ak0BHMOflmtZyd7ZIz4eGyJ0sV778&amp;h=AT0uDk2yCSVDwA_B86XHG1qaZjT2jm39v1koC_0Uz_sm7aZ17ZgOn3Mg7P8qCC1pJNknv8PDaXz2xKTtAuwYuccdjw-SGbyR3Qq1Gpw4AvldqEUL6cCQlytJ6HiZx9NvM_97_3TywdHLM1QTRMG-CQ) platforms, or another platform meeting industry standards, you may present this as an alternative protection instead of a pen test or vulnerability scan. To demonstrate this, you must submit the following evidence:

| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| testing-12.a.i, testing-12.b.i - Provide a written explanation (e.g., a policy or procedure document) that describes your vulnerability disclosure program. Your document should state that:&lt;br&gt;&lt;br&gt;• There are no exclusions to the scope of the VDP relevant to the way you process Platform Data&lt;br&gt;• Submitted (valid) vulnerabilities are assigned a severity score, e.g., using CVSS 3.1&lt;br&gt;• Vulnerabilities are resolved in a reasonable amount of time, typically fewer than 90 days after the submission date&lt;br&gt; | testing-12.a.ii, testing-12.b.ii - Provide screenshot proof of use of your vulnerability disclosure program:&lt;br&gt;&lt;br&gt;• A statement of scope and how that interrelates with the software used to process Platform Data, AND&lt;br&gt;• A report of the actual vulnerability submissions in the program over the past 12 months  from your DPA dispatch date. The report should include the vulnerability title, submission date, resolution date (if resolved) and severity category / score. Our team will check whether or not that there is actual ongoing vulnerability research and reporting within the past 12 months prior to your DPA dispatch date, typically indicated by at least 1 valid vulnerability report per month. If you have more than one app, we would typically expect the number of vulnerability reports through your program to scale up proportionally.&lt;br&gt;&lt;br&gt;&lt;br&gt;[Remove or redact sensitive information](https://developers.facebook.com/docs/development/maintaining-data-access/data-protection-assessment/data-security#redact-evidence) such as detailed vulnerability reproduction steps from the evidence before submitting. |

**testing1-12.c Requirements**

If you store Platform Data in a backend environment hosted by a cloud provider, you must test your cloud configuration for security issues. This requirement applies irrespective of the hosting approach (e.g., BaaS, PaaS, IaaS, self hosted, or hybrid), except if you are using a no-code backend.

| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| testing-12.c.i - Provide a written explanation (e.g., a policy or procedure document) that states how you test the cloud environment you use to process Platform Data for security misconfigurations.&lt;br&gt;&lt;br&gt;The following testing procedures should all be included in your written explanation:&lt;br&gt;• Test for security vulnerabilities at least once every 12 months&lt;br&gt;• Have a process to triage the findings based on severity&lt;br&gt;• How you ensure that high severity vulnerabilities, which could lead to unauthorized access to Platform Data, are remediated in a timely manner&lt;br&gt; | testing-12.c.ii - Provide evidence (e.g., a summary of a NCC Scout Suite test with a date) that shows how you test the cloud environment you use to process Platform Data for security misconfigurations. Please ensure all uploaded evidence includes a timestamp.&lt;br&gt;&lt;br&gt;The following details should be included in your evidence:&lt;br&gt;&lt;br&gt;• An explanation of the scope and testing methodology&lt;br&gt;• The date when the testing activity took place (To be acceptable, the date cannot be more than 12 months old from our DPA notification date)&lt;br&gt;• An output of identified vulnerabilities, including severity level (or category) for each finding.  Where applicable, include a summary of any unremediated Critical or High vulnerabilities, and whether any of those vulnerabilities present a risk of unauthorized access to Platform Data.&lt;br&gt;&lt;br&gt;&lt;br&gt;[Remove or redact sensitive information](https://developers.facebook.com/docs/development/maintaining-data-access/data-protection-assessment/data-security#redact-evidence) such as detailed vulnerability reproduction steps from the evidence before submitting. |

### External resources

Not familiar with application and cloud security testing? Review these resources.

* [NIST: Open source and commercial SAST tools ](https://www.nist.gov/itl/ssd/software-quality-group/source-code-security-analyzers?fbclid=IwAR1VZ6_Kh35ZXkZ4CIVNnBtMI7YngIQEinvpeZGBcHGvyFUOzqrO1nZkiBU)
* [NIST: NISTIR 8397 Guidelines on Minimum Standards for Developer Verification of Software](https://nvlpubs.nist.gov/nistpubs/ir/2021/NIST.IR.8397.pdf)
* [OWASP: OWASP Code Review Guide v2 ](https://owasp.org/www-pdf-archive/OWASP_Code_Review_Guide_v2.pdf)
* [GitHub: AKS DevSecOps Workshop ](https://azure.github.io/AKS-DevSecOps-Workshop/modules/Module3/intro.html)
* [BugCrowd:10 Essentials to Look for in a Crowdsourced Security Platform](https://www.bugcrowd.com/blog/10-essentials-to-look-for-in-a-crowdsourced-security-platform/)
* [AWS Security Hub: SEC 11. Incorporate and validate the security properties of applications throughout the SSDLC ](https://docs.aws.amazon.com/wellarchitected/latest/framework/sec-11.html)
* [NCC Group: Best Practices of the use of SAST within a Real-World SDLC ](https://research.nccgroup.com/wp-content/uploads/2020/07/ncc-group-best-practices-for-static-code-aanalysis.pdf)
* [CIS Benchmarks: Foundational Cloud Security with CIS Benchmarks ](https://www.cisecurity.org/insights/blog/foundational-cloud-security-with-cis-benchmarks)
* [Scout Suite: GitHub - nccgroup/ScoutSuite: Multi-Cloud Security Auditing Tool](https://github.com/nccgroup/ScoutSuite)

### Evidence examples
[testing1-12 evidence examples](https://developers.facebook.com/docs/resp-plat-initiatives/data-protection-assessment/data-security/version3.1#312)

## Access Token and App Secret Questions

### All questions

accesstoken-13.a, appsecret-13.b.i, accesstoken-13.c, accesstoken-13.c.i, accesstoken-13.c.ii, appsecret-13.d, appsecret-13.d.i, appsecret-13.d.ii

### Summary

App secrets and access tokens are fundamental to the security of how Meta APIs make decisions about what actions to allow. If an unauthorized party gains access to these credentials they could call Meta APIs - impersonating the real developer - and take any of the actions that we have granted the app (e.g., reading data from Meta APIs about an app’s users).

- You have access to sensitive credentials as a part of the use of Meta’s Platform. Specifically:

- Access Token - When people authorize the app, the software gets a credential called an access token that’s used in subsequent API calls

- App Secret - Meta shares an app secret with developers with the expectation that only trusted parties (e.g., app admins) within the organization have access to this secret

- An unauthorized party who is able to read these sensitive credentials can use them to call Meta APIs as if they are you (this is sometimes called token impersonation) leading to unauthorized access to Platform Data

- Therefore these credentials must be protected from unauthorized access to prevent impersonation

This section asks questions about how you protect these attributes on the client and server side, as applicable.

### Additional guidance

**accesstoken-13.c Requirements**

This question pertains to protecting Meta User Access Tokens stored in your backend environment.

| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| accesstoken-13.c.i -  Provide a written explanation (e.g., a policy or procedure document) that states how you protect these access tokens.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;Access tokens are fundamental to the security of Meta&#039;s APIs.&lt;br&gt;&lt;br&gt;We require developers to protect access tokens from unauthorized access.&lt;br&gt;&lt;br&gt;Your written explanation should include:&lt;br&gt;&lt;br&gt;1. Description of how user access tokens are protected from unauthorized read access; and&lt;br&gt;2. A requirement that user access tokens must never be written to log files in cleartext (unencrypted) form. | accesstoken-13.c.ii - Provide screenshot proof that Meta User Access Tokens are:&lt;br&gt;&lt;br&gt;* Stored in a data vault / secrets manager&lt;br&gt;OR&lt;br&gt;* Encrypted at the application or field/column level&lt;br&gt;&lt;br&gt;If access tokens are not encrypted/ protected server side, you must:&lt;br&gt;&lt;br&gt;• Store the app secret in a vault (or is using a Key Management System - KMS)&lt;br&gt;AND&lt;br&gt;• Enable the “Require App Secret” setting in their developer console&lt;br&gt;&lt;br&gt;&lt;br&gt;Make sure that you do not include (i.e., remove or redact) the plaintext values of any secrets or access tokens in the evidence that you submit. |

**appsecret-13.d Requirements**

This question pertains to storage of Meta App Secrets.

| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| appsecret-13.d.i - Provide a written explanation (e.g., a policy or procedure document) that states how you implement this protection.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;Your written explanation should include:&lt;br&gt;&lt;br&gt;1. Description of how the app secret is protected from unauthorized read access; and&lt;br&gt;2. A requirement that the app secret must never be written to log files in cleartext (unencrypted) form&lt;br&gt;&lt;br&gt;The app secret is fundamental to the security of Meta&#039;s APIs. We require developers to protect the app secret from unauthorized access. | accesstoken-13.d.ii - Provide screenshot proof that the Meta App Secret is either:&lt;br&gt;&lt;br&gt;* Stored in a data vault / secrets manager&lt;br&gt;OR&lt;br&gt;* Encrypted at the application or field/column level&lt;br&gt;&lt;br&gt;If you do not protect or encrypt the app secret, we require that:&lt;br&gt;&lt;br&gt;* The “Desktop/Native” Type is enabled in your Meta developer console.&lt;br&gt;&lt;br&gt;Make sure that you do not include (i.e., please remove or redact) the plaintext values of any secrets or access tokens in the evidence that you submit. |

**Acceptable Alternative Protections**

- If you do not protect access tokens stored server side with a data vault or via app-level encryption, you may:

- Protect the app secret by using a vault or application encryption where the key is only accessible to the app

- AND configure the app to [require app secret proof for all API calls to Meta](https://developers.facebook.com/docs/graph-api/securing-requests%20#require-proof)

- If approach #1 above is not viable (i.e., cannot require app secret proof because it would block certain necessary API calls), then Meta will consider any other controls that you have in place to limit the risk of unauthorized use of the access tokens compared to the risk of misuse of stored access tokens.

### External resources

* [OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
* [NIST Digital Identity Guidelines](https://pages.nist.gov/800-63-3/sp800-63b.html)
* [AWS Secrets Manager Service Provider Documentation](https://aws.amazon.com/secrets-manager/resources/?secrets-whats-new.sort-by=item.additionalFields.postDateTime&amp;secrets-whats-new.sort-order=desc&amp;aws-secrets-manager-resources-blog.sort-by=item.additionalFields.createdDate&amp;aws-secrets-manager-resources-blog.sort-order=desc)
* [GCP Secret Manager Service Provider Documentation](https://cloud.google.com/security/products/secret-manager)

### Evidence examples
[accesstoken-13 evidence examples](https://developers.facebook.com/docs/resp-plat-initiatives/data-protection-assessment/data-security/version3.1#313)

## MFA Questions - Protecting Accounts from Unauthorized Access

### All questions

mfa1-15.a.i, mfa1-15.a.ii, mfa1-15.a.iii, mfa1-15.b.i, mfa1-15.b.ii, mfa1-15.b.iii, mfa1-15.e, mfa-15.e.iii, mfa-15.e.iv

### Summary

A common technique used by adversaries to gain access to confidential data is to start by gaining access to tools that a developer uses to build or operate their app/system. Sophisticated tools exist to hack into accounts that are protected only by password and present the risk of account takeover attacks. The intent of these questions is to ensure developers have implemented  multi-factor authentication to mitigate these risks.

This section asks about how you protect accounts against unauthorized access using multi factor authentication or another approach.

### Additional guidance

Note that your Q15 requirements may change depending on if Meta Platform Data is stored in your backend environment.

**mfa1-15.a.i Requirements**

Related to an organization’s processing of Platform Data, remote access to all tools listed above (if applicable) must be protected with multi factor authentication (i.e., not simply a password):

| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| mfa1-15.a.ii -  Provide a written explanation (e.g., a policy or procedure document) that states your requirements for multi-factor authentication (MFA) or an alternative policy that meets our requirements below.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;If your organization does not enforce MFA, the alternative protections must include all of the following:&lt;br&gt;&lt;br&gt;• Password Specific Requirements:&lt;br&gt;• Enforce password length of at least 14 characters;&lt;br&gt;• Require at least one number and/or special character;&lt;br&gt;• Restrict password reuse, or formally define number of iterations before reuse is allowed; and&lt;br&gt;• Require a minimum password age of 1 day (i.e., if a password is changed, the system doesn’t allow it to be changed again for 24 hours).&lt;br&gt;• Failed Login Attempt Requirements:&lt;br&gt;• Authentication backoff delays OR temporary account lockouts due to consecutive failed login attempts.&lt;br&gt;• CIS recommends time doubling throttling (in minutes) between login retries (e.g., 0, 1, 2, 4, 8, etc.) or enforcing a temporary account lockout (15 minutes or more) after 5 consecutive failed login attempts.&lt;br&gt;• Automatic hard account lockout (i.e., IT admin reset required) upon 10 consecutive failed login attempts.&lt;br&gt;&lt;br&gt;&lt;br&gt;Your explanation should include:&lt;br&gt;&lt;br&gt;Your authentication requirements for all access to any collaboration and communication tools and code repositories.&lt;br&gt;&lt;br&gt;Please highlight or circle where in your policy these conditions are outlined. | mfa1-15.a.iii - Provide at least one piece of evidence (e.g., a tool configuration or screen capture from your application) that shows how you implement multi-factor authentication or other measures to prevent account takeover.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;Your evidence should show how you use authentication to protect all access to any collaboration, communication tools, and code repositories.&lt;br&gt;&lt;br&gt;Please note:&lt;br&gt;&lt;br&gt;1. Screenshot evidence of a single MFA-log in flow cannot be considered for this question, and&lt;br&gt;2. Evidence provided must reflect how you enforce MFA across your organization (e.g., a managed configuration or setting). |

| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| mfa1-15.b.ii - Provide a written explanation (e.g., a policy or procedure document) that states your requirements for multi-factor authentication (MFA) or an alternative policy that meets our requirements below.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;If your organization does not enforce MFA, the alternative protections must include all of the following:&lt;br&gt;&lt;br&gt;• Password Specific Requirements:&lt;br&gt;• Enforce password length of at least 14 characters;&lt;br&gt;• Require at least one number and/or special character;&lt;br&gt;• Restrict password reuse, or formally define number of iterations before reuse is allowed; and&lt;br&gt;• Require a minimum password age of 1 day (i.e., if a password is changed, the system doesn’t allow it to be changed again for 24 hours).&lt;br&gt;• Failed Login Attempt Requirements:&lt;br&gt;• Authentication backoff delays OR temporary account lockouts due to consecutive failed login attempts.&lt;br&gt;• CIS recommends time doubling throttling (in minutes) between login retries (e.g., 0, 1, 2, 4, 8, etc.) or enforcing a temporary account lockout (15 minutes or more) after 5 consecutive failed login attempts.&lt;br&gt;• Automatic hard account lockout (i.e., IT admin reset required) upon 10 consecutive failed login attempts.&lt;br&gt;&lt;br&gt;&lt;br&gt;Your explanation should include:&lt;br&gt;&lt;br&gt;Your authentication requirements for all access to any collaboration and communication tools, code repositories, software deployment tools, and backend administrative tools.&lt;br&gt;&lt;br&gt;Please highlight or circle where in your policy these conditions are outlined. | mfa1-15.b.iii -Provide at least one piece of evidence (e.g., a tool configuration or screen capture from your application) that shows how you implement multi-factor authentication or other measures to prevent account takeover.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;Your evidence should show how you use authentication to protect all access to any collaboration and communication tools, code repositories, software deployment tools, and backend administrative tools.&lt;br&gt;&lt;br&gt;Please note:&lt;br&gt;&lt;br&gt;1. Screenshot evidence of a single MFA-log in flow cannot be considered for this question, and&lt;br&gt;2. Evidence provided must reflect how you enforce MFA across your organization (e.g., a managed configuration or setting). |

| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| mfa-15.e.iii - Provide a written explanation (e.g., a policy or procedure document) that states your requirements for multi-factor authentication (MFA) or an alternative policy that meets our requirements below.&lt;br&gt;Explanation:&lt;br&gt;Your explanation should include your authentication requirements for all remote access to servers via a tool like SSH.&lt;br&gt;&lt;br&gt;If your organization does not enforce MFA, the alternative protections must include all of the following:&lt;br&gt;&lt;br&gt;• Password Specific Requirements:&lt;br&gt;• Enforce password length of at least 14 characters;&lt;br&gt;• Require at least one number and/or special character;&lt;br&gt;• Restrict password reuse, or formally define number of iterations before reuse is allowed; and&lt;br&gt;• Require a minimum password age of 1 day (i.e., if a password is changed, the system doesn’t allow it to be changed again for 24 hours).&lt;br&gt;• Failed Login Attempt Requirements:&lt;br&gt;• Authentication backoff delays OR temporary account lockouts due to consecutive failed login attempts.&lt;br&gt;• CIS recommends time doubling throttling (in minutes) between login retries (e.g., 0, 1, 2, 4, 8, etc.) or enforcing a temporary account lockout (15 minutes or more) after 5 consecutive failed login attempts.&lt;br&gt;• Automatic hard account lockout (i.e., IT admin reset required) upon 10 consecutive failed login attempts.&lt;br&gt; | mfa-15.e.iv -  Provide at least one piece of evidence (e.g., a tool configuration or screen capture from your application) that shows how you implement multi-factor authentication or other measures to prevent account takeover.&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;Your explanation should include your authentication requirements for all remote access to servers via a tool like SSH.&lt;br&gt;&lt;br&gt;Please note:&lt;br&gt;&lt;br&gt;1. Screenshot evidence of a single MFA-log in flow cannot be considered for this question, and&lt;br&gt;2. Evidence provided must reflect how you enforce MFA across your organization (e.g., a managed configuration or setting). |

### External resources

Not familiar with protecting accounts from unauthorized access? Review these resources.

* [NIST: NIST SP 800-218 ](https://csrc.nist.gov/pubs/sp/800/218/final)
* [OWASP: Enforce Access Controls](https://owasp.org/www-project-proactive-controls/v3/en/c7-enforce-access-controls)

### Evidence examples
[mfa1-15 evidence examples](https://developers.facebook.com/docs/resp-plat-initiatives/data-protection-assessment/data-security/version3.1#315)

## Maintaining Questions - Access Controls

### All questions

maintaining-16, maintaining-16.a.i, maintaining-16.a.ii

### Summary

Accounts are the basic unit of management for granting people access to systems, data, and administrative functions. Having good account management hygiene is an important part of preventing unauthorized use of accounts to gain access to Platform Data. The intent of this question is to ensure developers are following the principle of least privilege and have a systematic way for managing accounts, granting permissions or privileges, and revoking access when it’s no longer needed.

This section asks about the systems and processes you use to manage access to your systems / tools.

### Additional guidance

You must have a tool or process for managing accounts for each of the these tools/systems/apps:

* Those used to communicate with one another, e.g., Slack or business email
* Those used to ship software, e.g. code repository and
* Administer and operate the system (as applicable to processing Platform Data)

You must regularly review (i.e., not less than once every 12 months) access grants and have a process for revoking access when: (1) it’s no longer required, (2) no longer being used, and (3) when a person departs the organization

Meta does not require:

* That any particular tool be used – a developer may use a directory product like Google Cloud identity or Microsoft Azure Active Directory, a cloud product like AWS Identity and Access Management (IAM), or use a spreadsheet that is kept up to date regularly.
* That there be a single consolidated tool for managing accounts across these various access types.

**maintaining-16.a Requirements**

| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| maintaining-16.a.i - Provide a written explanation (e.g., a policy or procedure document) that covers your account management practices. We expect this document to contain procedures for:&lt;br&gt;&lt;br&gt;* Revoking access that is no longer required&lt;br&gt;* Revoking access that is no longer being used&lt;br&gt;* Revoking access promptly when a person leaves your organization (e.g., when an employee resigns or is terminated)&lt;br&gt;* Reviewing access at least once every 12 months | maintaining-16.a.ii - Provide evidence from AT LEAST ONE of the following tools or processes that is in place to manage accounts (or denote as not applicable to the environment):&lt;br&gt;&lt;br&gt;* Business email and collaboration tools&lt;br&gt;* Code repository&lt;br&gt;* Cloud/server deployment tools&lt;br&gt;* Cloud/server administrative portal&lt;br&gt;* Cloud/server remote login (e.g., SSH or remote desktop)&lt;br&gt;&lt;br&gt;Your evidence must show how you initiate access revocation. For example:&lt;br&gt;&lt;br&gt;* A revoke/delete access button, or&lt;br&gt;* Triggering an automated revocation flow. |

### External resources

Not familiar with access controls? Review these resources.

* [NIST: NIST SP 800-218 ](https://csrc.nist.gov/pubs/sp/800/218/final)
* [OWASP: Enforce Access Controls](https://owasp.org/www-project-proactive-controls/v3/en/c7-enforce-access-controls)

### Evidence examples
[maintaining-16 evidence examples](https://developers.facebook.com/docs/resp-plat-initiatives/data-protection-assessment/data-security/version3.1#316)

## Patches and Mobile Questions - Keep Software Up to Date

### All questions

patches1-17.a, updated-17.a.i, updated-17.a.ii, mobile1-17.b, mobile-17.b.i, mobile-17.b.ii, patches1-17.c, antivirus-17.c.i, antivirus-17.c.ii

### Summary

Software components are routinely updated or patched to resolve security vulnerabilities, and eventually these components will reach their end of life when they are no longer supported. Developers who package or rely on these components must keep up to date to avoid running software with known vulnerabilities. Therefore, developers using Meta’s platform must have a systematic way to identify, prioritize, and apply patches for all relevant parts of their tech stack.

This section asks about the systems and processes you use to keep software up to date.

### Additional guidance

For the following software components, as applicable, you must have a defined and repeatable way of identifying available patches that resolve security vulnerabilities, prioritizing based on risk, and applying patches as an ongoing activity:

1. Libraries, SDKs, packages, app containers, and operating systems used in a cloud or server environment
2. Libraries, SDKs, packages used on client devices, e.g., within mobile apps
3. Operating systems and applications used by members to build and operate the app/system, e.g., operating systems and browsers running on employee laptops

Meta does not require the use of any particular tool for these activities. It’s common that an organization would use different approaches for keeping different types of software up to date (e.g., libraries that are packaged with the app vs operating system updates for employee laptops).

This requirement applies irrespective of the hosting approach (e.g., BaaS, PaaS, IaaS, self hosted, or hybrid), although the set of components that you are responsible for keeping up to date will vary
Start by identifying the in-scope types of software in the environment, e.g., Libraries, SDKs, Packages, Virtual Machine images, app containers, and operating systems, Browsers, operating systems, and other applications used by the employees / contributors.

You may have one or more tools that you use for the following activities:

* Inventory - document via a screenshot or document that a tool or process that, ultimately, represents a list of in-scope libraries, packages, SDKs, containers, app servers and operating systems that need to be patched. There needs to be inventories for a representative of the software types (e.g., cloud app(s), client app(s), employee devices).
* Identifying available software patches - a tool or process must exist for identifying security patches that exist that are relevant to the inventory.
* Prioritizing - there needs to be a tool or process (e.g., Jira tickets, GitHub issues, tracking spreadsheet) by which relevant patches are assigned a priority
    * Patching
    * Document via a screenshot or document that demonstrates that, after relevant patches have been identified and prioritized, that they are then rolled out into the various destinations.
* Include policies around time to resolve and use of End of Life (EOL) software.

**patches1-17.a Requirements related to third-party software in your backend environment, if applicable:**

| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| updated-17.a.i -  Provide a written explanation (e.g., a policy or procedure document) that states how you keep your code and backend environment updated.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;Your written explanation must include all of the following:&lt;br&gt;&lt;br&gt;1. Have a defined and repeatable way of identifying patches in third-party software that resolve security vulnerabilities;&lt;br&gt;2. Prioritize available patches based on risk (e.g., based on CVSS severity); and&lt;br&gt;3. Apply patches as an ongoing activity. | updated-17.a.ii - Provide evidence (e.g., a tool configuration or screen capture from your application with a date) that shows how you keep your code and backend environment updated. Please ensure all uploaded evidence includes a timestamp.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;The following details must be included in your evidence:  &lt;br&gt;&lt;br&gt;• Scope and tooling context&lt;br&gt;• If you are uploading output from a tool (e.g., a software composition analysis scanner or package audit), provide a brief explanation of what the tool is and what it is scanning. This helps us confirm the evidence is relevant to your backend environment.&lt;br&gt;• If you are uploading a patch or vulnerability tracker, ensure it clearly references the backend components being tracked. The tracker must at minimum track the following categories:&lt;br&gt;• A list of relevant dependencies&lt;br&gt;• Date dependency was checked&lt;br&gt;• Version or dependency status&lt;br&gt;• Update/ Remediation Status&lt;br&gt;• Criticality/ Severity&lt;br&gt;&lt;br&gt;• Date of evidence&lt;br&gt;• Evidence must include a date showing when it was produced.&lt;br&gt;• To be acceptable, the date cannot be more than 12 months old from our DPA notification date.&lt;br&gt;• Severity classification&lt;br&gt;• Evidence must show that identified vulnerabilities include a severity score or category (e.g., Critical, High, Medium, Low).&lt;br&gt;• For any unremediated Critical or  High severity vulnerabilities, provide one of the following:&lt;br&gt;• (1) A statement confirming that Critical or High severity vulnerabilities have been remediated; or&lt;br&gt;• (2) A statement confirming that Critical or High severity vulnerabilities do not present a risk of unauthorized access to Platform Data; or&lt;br&gt;• (3) Evidence that open Critical or High severity vulnerabilities are within defined remediation SLAs.&lt;br&gt;&lt;br&gt;&lt;br&gt;&lt;br&gt;Evidence that does not include severity classifications for identified vulnerabilities is considered incomplete and will require additional follow-up. |

**mobile1-17.b Requirements related to third-party code in your mobile app, if applicable:**
| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| mobile-17.b.i - Provide a written explanation (e.g., a policy or procedure document) that states how you keep third-party code updated in your mobile app.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;Your written explanation must include all of the following:&lt;br&gt;&lt;br&gt;1. Have a defined and repeatable way of identifying patches in mobile third-party software that resolve security vulnerabilities;&lt;br&gt;2. Prioritize available patches based on risk (e.g., based on CVSS severity); and&lt;br&gt;3. Apply patches as an ongoing activity | mobile-17.b.ii - Provide evidence (e.g., a tool configuration or screen capture from your application with a date) that shows how you keep third-party code updated in your mobile app. Please ensure all uploaded evidence includes a timestamp.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;The following details must be included in your evidence:  &lt;br&gt;&lt;br&gt;• Scope and tooling context&lt;br&gt;• If you are uploading output from a tool (e.g., a software composition analysis scanner or package audit), provide a brief explanation of what the tool is and what it is scanning. This helps us confirm the evidence is relevant to your backend environment.&lt;br&gt;• If you are uploading a patch or vulnerability tracker, ensure it clearly references the backend components being tracked. The tracker must at minimum track the following categories:&lt;br&gt;• A list of relevant dependencies&lt;br&gt;• Date dependency was checked&lt;br&gt;• Version or dependency status&lt;br&gt;• Update/ Remediation Status&lt;br&gt;• Criticality/ Severity&lt;br&gt;&lt;br&gt;• Date of evidence&lt;br&gt;• Evidence must include a date showing when it was produced.&lt;br&gt;• To be acceptable, the date cannot be more than 12 months old from our DPA notification date.&lt;br&gt;• Severity classification&lt;br&gt;• Evidence must show that identified vulnerabilities include a severity score or category (e.g., Critical, High, Medium, Low).&lt;br&gt;• For any unremediated Critical or  High severity vulnerabilities, provide one of the following:&lt;br&gt;• (1) A statement confirming that Critical or High severity vulnerabilities have been remediated; or&lt;br&gt;• (2) A statement confirming that Critical or High severity vulnerabilities do not present a risk of unauthorized access to Platform Data; or&lt;br&gt;• (3) Evidence that open Critical or High severity vulnerabilities are within defined remediation SLAs.&lt;br&gt;&lt;br&gt;&lt;br&gt;&lt;br&gt;Evidence that does not include severity classifications for identified vulnerabilities is considered incomplete and will require additional follow-up. |

**patches1-17.c Requirements related to other third-party software used by people in your organization to build and operate your app, if applicable:**

| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| antivirus-17.c.i - Provide a written explanation (e.g., a policy or procedure document) that describes how you keep third-party software and antivirus software on organizational devices updated.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;Your written explanation must include all of the following:&lt;br&gt;&lt;br&gt;1. Have a defined and repeatable way of identifying patches in third-party software that resolve security vulnerabilities;&lt;br&gt;2. Prioritize available patches based on risk (e.g., based on CVSS severity); and&lt;br&gt;3. Apply patches as an ongoing activity. | antivirus-17.c.ii -  Provide screenshot evidence that shows how you keep third-party software and antivirus software on organizational devices updated.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;The following details must be included in your evidence:&lt;br&gt;&lt;br&gt;1. A managed approach for how you maintain and patch your OS, browsers, or antivirus environments (e.g., Windows Update Server check (WSUS) or automatic antivirus updates); and&lt;br&gt;2. The date must be no earlier than 12 months prior to the date that we notified you about this assessment&lt;br&gt;&lt;br&gt;Evidence can come in the form of:&lt;br&gt;&lt;br&gt;• A tooling configuration that shows how you push OS/software updates across your organization such as Chef, OR&lt;br&gt;• A tooling configuration that shows that antivirus software is set to automatically update across your organization, OR&lt;br&gt;• A spreadsheet or equivalent tool for manually tracking what services you are using and what needs to be updated. The spreadsheet must at minimum track the following categories:&lt;br&gt;• A list of relevant software&lt;br&gt;• Date software was checked&lt;br&gt;• Version or software status&lt;br&gt;• Update/ Remediation Status&lt;br&gt;• Criticality/ Severity&lt;br&gt;&lt;br&gt; |

### External resources

Not familiar with keeping software up to date? Review these resources.

* [OWASP - OWASP Vulnerable Dependency Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Vulnerable_Dependency_Management_Cheat_Sheet.html)
* [OWASP OWASP Checking for Weaknesses in Third Party Libraries ](https://mas.owasp.org/MASTG/tests/ios/MASVS-CODE/MASTG-TEST-0085/#overview)
* [CSF Tools - 7: Continuous Vulnerability Management - CSF Tools](https://csf.tools/reference/critical-security-controls/version-8/csc-7/)
* [AWS - AWS SEC 11 incorporate and validate the security properties of applications throughout the design, development, and deployment lifecycle](https://docs.aws.amazon.com/wellarchitected/latest/framework/sec-11.html)

### Evidence examples
[Patches and Updated evidence examples](https://developers.facebook.com/docs/resp-plat-initiatives/data-protection-assessment/data-security/version3.1#317)

## Auditlog Questions

### All questions

auditlog-22, auditlog-22.a, auditlog-22.a.i, auditlog-22.b, auditlog-22.b.iv, auditlog-22.b.iii, auditlog-22.c, auditlog-22.d, auditlog-22.e.1, auditlog-22.e.ii, auditlog-22.e.iii, auditlog-22.f.1, auditlog-22.f.ii, auditlog-22.g, auditlog-22.g.i

### Summary

Without reliable log files it can be difficult to impossible for a developer to detect unauthorized access to Platform Data. Audit logs allow an organization to record the fact that an event occurred, e.g. that a particular user executed a query against database tables containing Platform Data. These logs can then support processes like triggering automated alerts based on suspicious activity or forensic analysis after a security incident has been identified. The intent of this question is to determine if developers have implemented controls around admin and application event logging to flag and escalate potential security incidents.

**“Admin audit log”** refers to records of actions taken by users with elevated privileges in data systems.

Properly configured, admin audit logs record the actions that a system administrator takes within the system.

Indicators of properly configured, admin audit logs include, but are not limited to:

* Executing programs or scripts;
* Creating or disabling accounts;
* Resetting passwords or changing multifactor authentication configurations; and/or
* Editing, moving, or deleting of log files within a system.

### Additional guidance

**auditlog-22 Requirements**
| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| auditlog-22.a - Provide a written explanation (e.g., a policy or procedure document)that describes your approach to collecting admin audit logs. Your response should:&lt;br&gt;&lt;br&gt;• State admin logs are collected, AND&lt;br&gt;• Describe what events are logged (unsuccessful login attempts, auditing / deleting of audit admin logs, and granting / revoking access admin privileges to accounts)&lt;br&gt; | auditlog-22.a.i - Provide screenshot evidence that shows how you collect admin audit logs. This evidence can come in the form of:&lt;br&gt;&lt;br&gt;• A tool dashboard showing admin audit logs are being collected along with the type of WHAT events are audited, OR&lt;br&gt;• Directory listing of files that indicate they are admin logs with date stamps&lt;br&gt;&lt;br&gt;&lt;br&gt;To be acceptable, the date in your logs must be no earlier than 3 months prior to the date that we notified you about this assessment. |

**auditlog-22.b Requirements**
| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| auditlog-22.b.iv - Provide a written explanation (e.g., a policy or procedure document) that describes your approach to collecting application event logs. Your response should:&lt;br&gt;&lt;br&gt;• State application event logs are collected, AND&lt;br&gt;• Describe that you log the following attributes:&lt;br&gt;• Event type&lt;br&gt;• Date and time&lt;br&gt;• Success or failure indicator&lt;br&gt;• Meta user ID (when shared with you)&lt;br&gt; | auditlog-22.b.iii - Provide screenshot evidence that shows how you collect application event logs. This evidence can come in the form of:&lt;br&gt;&lt;br&gt;• A tool dashboard showing application event logs are being collected along with the type of WHAT events are audited, OR&lt;br&gt;• Directory listing of files that indicate they are application event logs with date stamps&lt;br&gt;&lt;br&gt;&lt;br&gt;Evidence provided must meet the following requirements:&lt;br&gt;• Screenshots and logs must be within 3 months from the date you received your Data Protection Assessment&lt;br&gt;• Redacted logs are acceptable as long as the event type and date are displayed&lt;br&gt; |

**auditlog-22.e.1 Requirements**
| Policy/Procedure Evidence | Implementation Evidence |
| --- | --- |
| auditlog-22.e.ii - Provide a written explanation (e.g., a policy or procedure document) that describes your approach to reviewing application event logs. Your response should:&lt;br&gt;&lt;br&gt;• State application event logs are reviewed at least once every seven days, AND&lt;br&gt;• Describe the use of an automated solution/ program to review logs, eg. a security information and event management tool (SIEM)&lt;br&gt;&lt;br&gt;&lt;br&gt;Please note that due to anticipatedly large amounts of data we expect to be captured in application event logs, we will not accept responses that indicate reviews conducted are solely manual. | auditlog-22.e.iii - Provide screenshot evidence that shows how you review application event logs to find indicators of everyday security events or incidents that result in risk or damage.&lt;br&gt;&lt;br&gt;Evidence provided must meet the following requirements:&lt;br&gt;&lt;br&gt;An alert or output that demonstrates active use of an automated solution to detect and investigate security-relevant events found in your logs.&lt;br&gt;&lt;br&gt;Acceptable Evidence examples:&lt;br&gt;&lt;br&gt;• Command line tool output highlighting suspicious events&lt;br&gt;• A Jira ticket created as a result of log review findings&lt;br&gt;• A Slack notification or alert triggered by the log monitoring tool&lt;br&gt;&lt;br&gt;&lt;br&gt;The key is that the evidence demonstrates active use of an automated solution to detect and initiate a follow up resulting from security-relevant events found in your logs. |

**auditlog-22.f.1 Requirements**
| Policy/Procedure Evidence (no screenshot evidence needed): |
| --- |
| auditlog-22.f.ii - Provide a written explanation (e.g., a policy or procedure document) that states your approach for reviewing admin audit logs in order to look for signs that an administrative account may have been compromised or misused.&lt;br&gt;&lt;br&gt;Explanation:&lt;br&gt;&lt;br&gt;“Backend environment” refers to a cloud or server environment that your customers or clients can access remotely, such as a website or web API.&lt;br&gt;&lt;br&gt;Indicators that an administrator account may have been compromised or misused include, but are not limited to:&lt;br&gt;&lt;br&gt;* Unusual admin login patterns (new locations, unusual hours, failed attempts);&lt;br&gt;* Changes to access controls that could expose Platform Data to unauthorized users;&lt;br&gt;* New admin accounts or privilege escalations that were not expected; and/or&lt;br&gt;* Modifications to logging, monitoring, or security configurations.&lt;br&gt;&lt;br&gt;**Weekly Review Required:&lt;br&gt;We require that you review admin audit logs from your backend environment at least every 7 days.**&lt;br&gt;&lt;br&gt;Please highlight or circle where in your policy these conditions are outlined. |

**auditlog-22.g Requirements**
| Policy/Procedure Evidence (no screenshot evidence needed): |
| --- |
| auditlog-22.g.i - Provide a written explanation (e.g., a policy or procedure document) that states how you investigate a security event that indicates unauthorized access to Meta Platform Data may have occurred in your backend environment where such data is stored.&lt;br&gt;&lt;br&gt;Your approach should describe:&lt;br&gt;&lt;br&gt;1. Steps to determine valid or invalid (positive or false positive) security events, for example a triage process; and&lt;br&gt;2. Escalation steps, for example a process for tracking, investigating, and remediating security events and notifying appropriate internal stakeholders.&lt;br&gt;&lt;br&gt;*Reminder: If a security event or incident occurs, our [policies](https://developers.facebook.com/docs/graph-api/guides/secure-requests#require-the-proof) require you to promptly report it to us. * |

### External resources

Not familiar with audit logs? Review these resources:

* [Data Dog - Audit Logging Overview](https://www.datadoghq.com/knowledge-center/audit-logging/)
*[CIS - Center for Internet Security (CIS): Audit Log Management Policy Template](https://www.cisecurity.org/insights/white-papers/audit-log-management-policy-template-for-cis-control-8)
* [Worldbank: Practitioner&#039;s Guide: Tamper-proof logs](https://id4d.worldbank.org/guide/tamper-proof-logs)
* [CSF Tools - NIST Controls: Audit and Accountability](https://csf.tools/reference/nist-sp-800-53/r5/au/)
* [AICPA - SOC 2 AICPA Trust Criteria, specifically CC7.2 and CC7.3](https://us.aicpa.org/content/dam/aicpa/interestareas/frc/assuranceadvisoryservices/downloadabledocuments/trust-services-criteria-2020.pdf)
* [OWASP - OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)

The following resources are not available free-of-charge, but offer valuable information and guidance:

* [ISO 27001:2013](https://www.iso.org/obp/ui/#iso:std:iso-iec:27001:ed-2:v1:en)
* [Annex A.12.4 - Logging and Monitoring](https://www.isms.online/iso-27001/annex-a-12-operations-security/#what-is-annex-a-12-4)

### Evidence examples
[Q3.1-22 evidence examples](https://developers.facebook.com/docs/resp-plat-initiatives/data-protection-assessment/data-security/version3.1#3122)

## Security Processes Questions

### All questions

securityprocesses-23

### Summary

Ensuring personnel are properly trained in the safe handling and protection of confidential data, including Platform Data, along with recognizing signs of potential compromise will reduce the likelihood a security incident.

### Changes from prior version

* This section is new as of questionnaire v3.

### Additional guidance

None

### External resources

Not familiar with personnel security? Review these resources:

* [CSF Tools - CSF Tools: Personnel Security](https://csf.tools/reference/nist-sp-800-53/r5/ps/)
* [Information Security Program - Personnel Security Policy Best Practices](https://informationsecurityprogram.com/personnel-security-policy-best-practices/)
* [IFSec Global - How a personnel security policy can combat the insider threat](https://www.ifsecglobal.com/security/personnel-security-policy-combat-insider-threat/)

### Evidence examples

Developers are not required to provide evidence in response to this question.
