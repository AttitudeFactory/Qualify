# Data Use Checkup FAQ



## General

**What’s the difference between Data Use Checkup and App Review?**

Data Use Checkup and App Review are two distinct yet related processes.

- App Review is an approval process through which we verify that your planned app uses our Products and APIs in accordance with allowed usage.

- After platform access is granted, Data Use Checkup is an annual process for developers to certify that their continued use of and access to specific data via Meta APIs is in compliance with our Meta Platform Terms and Developer Policies, and to validate that personal data received from Meta will be processed and transferred securely.

**Why do I need to complete the data handling questions in the DUC?**

DUC is a requirement for apps that have been published live with a use case, or that have [advanced access](https://developers.facebook.com/docs/graph-api/overview/access-levels) to any [permissions](https://developers.facebook.com/docs/permissions/reference) and/or [features](https://developers.facebook.com/docs/features-reference) at any time since the previous DUC was completed, or since the app went live, if this is the first assessment.

**What is the difference between an app in Development Mode vs Live Mode?**

Development Mode and Live Mode are two app modes that have implications on app functionality and Data Use Checkup.
Development Mode is typically used to test, explore API products/permissions and complete App Review. Apps in Dev Mode cannot access personal data of users who do not have a role on the app.
Live Mode is used for production scenarios and apps in live mode can access personal data of all users. Only Live Mode apps require Data Use Checkup.

**Can I complete DUC for multiple apps at once?**

Yes, developers who manage multiple apps will have the option to complete Data Use Checkup for multiple apps at once. You can do so by going to your [“My Apps” page in the App Dashboard](https://developers.facebook.com/apps/) or your Required Actions Dashboard. From there, you will see all apps for which you are an admin, and select the apps you want to include together in the same DUC submission.

**Who should complete the Data Use Checkup process?**

The process should be completed by the [app administrator](https://developers.facebook.com/docs/apps/security#admin). App administrators should be in a position of authority to act on behalf of your organization.

**Are there documented requirements that Meta expects me to comply with?**

While we provide guidelines and recommendations in our [Best Practices](https://developers.facebook.com/documentation/resp-plat-initiatives/individual-processes/data-use-checkup/tutorial) documentation, we do not have specific requirements documentation that we expect all developers to comply with. We encourage you to carefully review our policies and ensure your app meets our guidelines before submitting. Additionally, you may find it helpful to post any questions or concerns you have in our [Developer Community Forum](https://developers.facebook.com/community/), where other developers can provide insights and assistance.  

**I have already provided answers about service providers in the Data Protection Assessment. Why is this being asked again?**

The data handling questions regarding data processors are different from and supplement the service provider questions in the Data Protection Assessment. Additionally, the data handling questions are designed to validate that personal data received from Meta will be processed and transferred securely and in compliance with Meta’s [Platform Terms](https://developers.facebook.com/terms) and [Developer Policies](https://developers.facebook.com/devpolicy) while the Data Protection Assessment asks developers about their data use, sharing and data security with regard to Platform Data.  

## Process

**What does the Data Use Checkup process entail?**

In order to complete DUC, an app admin needs to:

1. Examine  previously approved or existing permissions, features and products.

2. Certify the app follows the allowed usage.

3. Certify that you are following the Meta Platform Terms and Developer Policies, together with all other applicable terms and policies.

4. Answer questions about your [data handling practices](https://developers.facebook.com/docs/development/release/data-handling-questions).

**How can I see which of my apps need to complete Data Use Checkup?**

You can see all apps that require Data Use Checkup and other required actions by going to the [&quot;My Apps&quot; page in the App Dashboard](https://developers.facebook.com/apps/). There, you can see all apps you manage and filter the list to see all apps with required actions.

**I don’t have access to an app I need to complete the Data Use Checkup for. How can I regain admin status?**

If you are unable to access an app and need to regain admin status, please use the [form](https://developers.facebook.com/forms/disconnected-app-admin).

**Are the permissions I see in Data Use Checkup the ones I have access to, or the ones I’m actively using?**

Data Use Checkup will surface all permissions your app has access to, regardless of whether the app is actively using them. We recommend taking this opportunity to audit your integration, better understand your app’s capabilities, and remove access to any permissions you don’t need.  

**How can I tell if I’m using these permissions?**

You can see usage levels for each permission in the “Permissions and Features” section of the App Dashboard. Once you log in, click “App Review” on the left side of the page, then select “Permissions and Features” from the dropdown. You’ll see a column for “API calls,” which will have a green check mark if our logging shows that you’re actively using the permission. Please remember this is just an estimate — you should consult with your development team to see if the permission is required for your integration.

**What should I do if I’m not using a permission that shows up in Data Use Checkup? Can I remove it?**

If you are not using a permission, you should first remove the permission using the App Dashboard (click “My Permissions and Features” from the left-side dropdown under “App Review”). Then you can certify the remaining permissions and features you are still using.

However, there are some auto-granted permissions that cannot be removed and you may be asked to certify for. If you haven’t used this data, you should still feel comfortable completing this process, since certifying indicates that any use of the permission is in compliance, which includes no use.

**I have decided to remove one or more permissions. Do I have to certify a removed permission?**

No. After you remove the permission in the App Dashboard, you can refresh the Data Use Checkup page and the permission you removed should disappear.

**Can I certify on behalf of my business or do I need to certify for each app?**

You must certify on behalf of every app your business manages.

**If there are multiple admins on my app, who should certify?**

Any app administrator can certify for the app. If you have multiple admins for an app, only one of them needs to certify.

**Can I complete the checkup partially/for select permissions or apps, do I need to certify for all at once?
**

You will need to complete the checkup for each app you manage (each app may have multiple permissions).

**Will I need to certify for all permissions I have access to, or only certain types?**

You will be prompted to certify for all permissions you had access to.  

**Why do I have to certify my use of permissions like email and profile picture, when I never requested these in the first place?**

Meta requires developers to certify for these auto-granted “basic” permissions because they are widely used and provide access to user data. However, if you haven’t used this data, you should still feel comfortable completing this process, since certifying indicates that any use of the permission follows our Terms and Policies, which includes no use.

**Do I need to sign the supplemental terms as part of accepting the Platform Terms in the Data Use Checkup flow?**

No.  

**Do I have to certify for all permissions, or just permissions that provide access to user data?**

You will have to complete Data Use Checkup for all permissions your app has access to.  

**Can Meta provide examples of acceptable data handling practices or responses?**

We are unable to disclose specific details about our review process or provide examples of responses. We encourage you to carefully review our [Best Practices](https://developers.facebook.com/documentation/resp-plat-initiatives/individual-processes/data-use-checkup/tutorial) and ensure that your app meets our guidelines before submitting it for review.  

**Will I receive feedback on my answers to individual questions?**

Your responses will be evaluated collectively. If your data handling practices are found to have an unacceptable level of risk, then your assessment will not be accepted and you will be asked to make changes to your data handling practices and re-submit the data handling questions.

**Will Meta request additional information from me about my responses?**

No, Meta will not request any additional information. If changes are required, you will be asked to update and re-submit your responses to the data handling questions. In many cases, results may be available shortly after submission, but it can also take up to a few days. In all cases you will receive an email and a message in Alerts Inbox communicating the results.

**Will Meta request evidence from me about my responses?**

No, Meta will not request any documentary evidence.  

## Submission

**How often do I need to complete the Data Use Checkup?**

This is an annual requirement.

**Can I save my progress and complete it over multiple sessions?**

Yes, the form is auto-saved. If you leave the form and come back, it will reload the previous auto-saved state.

**When should I expect to have to complete the Data Use Checkup?**

Deadlines are unique to each app and will be displayed in your developer notification, the app dashboard banner, and the apps panel. You, or another app [Administrator](https://developers.facebook.com/documentation/development/build-and-test/app-roles#administrator), will receive a developer notification in your email and [Alerts Inbox](https://developers.facebook.com/documentation/development/create-an-app/app-dashboard#alerts) 60 days before DUC is due, and reminders will be sent 30 days, 10 days, and 3 days before your DUC deadline.

**How long does it take to get the results of my submission?**

In many cases, results may be available shortly after submission, but it can also take up to a few days. In all cases you will receive an email and a message in Alerts Inbox communicating the results.

**Where can I check the status of my Data Use Checkup?**

You can check the status of your DUC on your App Dashboard. You will also receive a message in an email and your Alerts Inbox with the results.

**What happens if I don’t complete the Data Use Checkup by my deadline?**

If you do not complete DUC by your deadline, your app will be deactivated until DUC is completed. Extensions will not be provided.  

**What happens if I submitted my DUC, but I’ve been asked to improve my data handling practices?**

If you’ve been asked to improve your data handling practices, please review these [best practices](https://developers.facebook.com/docs/development/release/data-handling-questions/best-practices) and make any updates needed before re-submitting the data handling questions.  

**After Platform access is restricted, can I get it back?**

You may still be able to return to your App Dashboard, complete the Data Use Checkup and restore access. However, note that any app that becomes [inactive](https://developers.facebook.com/documentation/development/maintaining-data-access) must have their use cases, permissions and features re-approved through the App Review process. Additionally, inactive apps will need to complete Data Use Checkup before being reactivated. Meta recommends completing the Data Use Checkup prior to your deadline to avoid this scenario.

**If changes to data handling practices are required, how long do we have to update our practices?**

If changes to your data handling practices are required, you will have 20 calendar days to resubmit acceptable responses. During this period, your app will remain active and available to users while you work to address any issues raised by our review. You may resubmit your responses as many times as you need. However, after every third submission you must wait three calendar days before submitting new responses.  

