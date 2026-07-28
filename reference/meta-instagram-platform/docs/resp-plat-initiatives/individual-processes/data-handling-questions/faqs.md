# Data Handling Questions FAQs

Answers to frequently asked questions about the data handling questions process.

## General

[Why do I need to answer these data handling questions?](#faq_1298274367387195)

Completing our data handling questions is a requirement for:

Apps that request or have any access to use cases, [permissions](/docs/permissions/reference) and/or [features](/docs/features-reference) (for some apps this is called [advanced access](/docs/graph-api/overview/access-levels/#advanced-access)).

Apps that have been published live with a use case, or that have advanced access to [permissions](/docs/permissions/reference) and/or [features](/docs/features-reference). This must be completed annually as part of the Data Use Checkup (DUC).

[Permalink](#faq_1298274367387195)

[What is “Platform Data?”](#faq_901206014725054)

"Platform Data" means any information, data or other content that you obtain from us, through Platform or through your app, whether directly or indirectly and whether before, on or after the date you agree to these terms, including data anonymised, aggregated or derived from such data. Platform Data includes all access tokens, the app secret, Meta user IDs, email addresses, profile pictures and usernames.

Please note that Platform Data may include a subset of personal data or personal information that relates to an identified or identifiable person.

[Permalink](#faq_901206014725054)

[How is this different from App Review, Data Use Checkup and Data Protection Assessment?](#faq_165372342666465)

* [App Review](/docs/app-review) is a forward-looking process that enables us to verify that your planned app uses our Products and APIs in an approved manner.
* [Data Use Checkup](https://developers.facebook.com/blog/post/2020/09/10/data-use-checkup-rolling-out-broadly-facebook-platform-developers/) is an annual process for developers to self-certify that their continued use of and access to specific data via Meta APIs is in compliance with our [Meta Platform Terms](/terms) and [Developer Policies](/devpolicy).
* [Data Protection Assessment](/docs/development/maintaining-data-access/data-protection-assessment/) is a requirement for apps accessing certain advanced permissions that is designed to assess whether developers use, share and protect Platform Data in accordance with the [Meta Platform Terms](/terms).

[Permalink](#faq_165372342666465)

[What happens if I don’t answer these data handling questions?](#faq_1369228927264162)

You will not be granted advanced access. (Learn about [advanced access](/docs/graph-api/overview/access-levels), [permissions](/docs/permissions), and [features](/docs/features-reference/))

[Permalink](#faq_1369228927264162)

[What is the difference between Standard and Advanced Access?](#faq_516721887333017)

Access levels are an additional layer of Graph API authorization that apply to [permissions](/docs/permissions/reference) and [features](/docs/features-reference) for [Business](/docs/development/create-an-app/app-dashboard/app-types#business), [Consumer](/docs/development/create-an-app/app-dashboard/app-types#consumer), and [Gaming apps](/docs/development/create-an-app/app-dashboard/app-types#gaming-services). There are two access levels: [Standard](/docs/graph-api/overview/access-levels/#standard-access) and [Advanced](/docs/graph-api/overview/access-levels/#advanced-access).

Apps can request permissions with Advanced Access from any app user, and features with Advanced Access are active for all app users. Permissions with Standard Access, however, can only be requested from app users who have a role on the requesting app, and features with Standard Access are only active for app users who have a role on the app.

If your app will only be used by people who have a role on it, the permissions and features your app requires will only need Standard Access. If your app will be used by people who do not have a role on it, the permissions and features that your app requires will need Advanced Access.

[Permalink](#faq_516721887333017)

[If I create an app with a use case, will I have to answer data handling questions?](#faq_122532027608342)

If you create an app with a use case, you may be prompted to answer data handling questions before App Review.

[Permalink](#faq_122532027608342)

[How often can I submit my app for App Review?](#faq_544291958589966)

Meta allows developers to submit their apps for review without any limit on the number of successful submissions. However, only one submission is allowed at a time per app, and submissions are limited for apps that have 5 rejected submissions in the previous 7 calendar days.

[Permalink](#faq_544291958589966)

## Completing the questions

[When will I be prompted to complete these data handling questions?](#faq_1214896306058832)

You may be prompted to answer questions about data handling when you request advanced access for a new or existing app. Beginning September 5, some developers may also be required to answer data handling questions during their annual Data Use Checkup.

[Permalink](#faq_1214896306058832)

[Do I need to complete these data handling questions if I only need Standard Access to permissions?](#faq_1382347545891406)

No, you will not be prompted to answer data handling questions if you only need Standard Access to permissions.

[Permalink](#faq_1382347545891406)

[What is a data controller?](#faq_729369698670300)

A data controller is the entity that exercises overall control over the purposes and means of the processing of personal data. Refer to definitions in the [General Data Protection Regulation (GDPR)](https://l.facebook.com/l.php?u=https%3A%2F%2Fgdpr-info.eu%2Fart-4-gdpr%2F&h=AUDamPade_H3qUUcsGEnZKoSRNQPU-VlyEWkk7hShnKZtWVrPnZ53o8orc311PKwpA7hpUaiBPAQXjOFEKjF3vUdfY888KApKVfQg9VGom8lGEcTGwV15b0wGgcaqKJ8IgyGJ96TflTQnsfA) and the [UK GDPR](https://l.facebook.com/l.php?u=https%3A%2F%2Fico.org.uk%2Ffor-organisations%2Fguide-to-data-protection%2Fguide-to-the-general-data-protection-regulation-gdpr%2Fkey-definitions%2Fcontrollers-and-processors%2F&h=AUDOk94AbYqVebhyiXl6b0FKyzNBm7EhhlQ1XgjgpSriuIogLUQyIVJNJtCgaUWnawDKlrOHDcxvZkos1sCowJnuu_7sdao543OD8Q8vBKD6ToorIwT4pUbtRZsi6YnI7nfx-2YKBuu9AYYC) for details and examples. Please ensure that you work with your legal team to understand this definition and how it applies to your business.

[Permalink](#faq_729369698670300)

[Why do I need to list a data controller?](#faq_1572103750049562)

For data controller, please provide the name of the legal entity that will control the purposes and means of processing the data made available to you by Meta through these [requested permissions](https://developers.facebook.com/docs/permissions/reference) or [features](https://developers.facebook.com/docs/features-reference).

[Permalink](#faq_1572103750049562)

[What is a data processor?](#faq_909183283691814)

A data processor is a person or business that provides you with services to help you process personal data you obtain from Meta. This may include Service Providers as defined in [Meta’s Platform Terms](https://developers.facebook.com/terms) as well as your own companies. Please ensure that you work with your legal team to understand this definition and how it applies to your business.

[Permalink](#faq_909183283691814)

[Why do I need to list a data processor or service provider?](#faq_851590216888978)

Processors and service providers are separate entities that, on your behalf, process the Meta Platform Data made accessible to you in order to provide you with a service. Please provide the names of any processors or service providers that will have access to the Meta Platform Data made accessible to you through the [requested permissions](https://developers.facebook.com/docs/permissions/reference) and/or [features](https://developers.facebook.com/docs/features-reference).

If you have no processors or service providers, please click “No.” By selecting “no,” you are confirming that you have no processors or service providers accessing the [Meta Platform Data](https://developers.facebook.com/terms/dfc_platform_terms/?glossary%3A%7E%3Atext=k.+%E2%80%9C-%2CPlatform+Data%2C-%E2%80%9D+means+any+information) for more information.

[Permalink](#faq_851590216888978)

[Can I save the questionnaire and complete it over multiple sessions?](#faq_3590191801209494)

The form is auto-saved. If you leave the questionnaire and come back, it will reload the previous auto-saved state.

[Permalink](#faq_3590191801209494)

[Can I use Google Translate when reviewing and completing data handling questions?](#faq_649214670521245)

The data handling questions have been translated into 17 languages. If your language is not available, you may use Google Translate outside of the question form. Using Google Translate inside the question form will cause a submission error.

[Permalink](#faq_649214670521245)

[Am I able to ask questions about the topics covered in the data handling questions?](#faq_1294062567884669)

* It is recommended that you consult with legal, policy, and privacy experts within your organization for guidance on how to answer these questions.
* Yes, if you need clarification about the data handling questions, you can reach out to Meta directly.

  + Within the Data Handling Questions, on the bottom of the page you will see a section titled **Need Help? Go to Developer Support**. Click on the link and you will receive a pop-up through which you can submit a clarifying question.
  + To access this feature, you will need to have a [Business Manager account](https://business.facebook.com/), and make sure to [add the app](https://www.facebook.com/business/help/2199735813629697?id=420299598837059) and [app admins](https://www.facebook.com/business/help/2169003770027706?id=2190812977867143). Please refer to those links for step-by-step guides.
  + You will receive a response from Meta via an email alert as well as a notification on the [App Dashboard](/https://developers.facebook.com/docs/development/create-an-app/app-dashboard).

[Permalink](#faq_1294062567884669)

## Submission

[How long do I have to submit the data handling questions?](#faq_243889534743436)

For apps that require access to use cases, permissions or features (for some apps this is called [advanced access](/docs/graph-api/overview/access-levels/#advanced-access)). There is no time limit for submitting the data handling questions. Your requested permission(s) will remain in Standard Access until your request has been reviewed and approved.

For apps that have been published live with a use case, or that have [advanced access](/docs/graph-api/overview/access-levels/#advanced-access) to permissions or features: You will receive notifications in your email and Alerts Inbox indicating that DUC is required. You have 60 days to submit your DUC with data handling questions. Your permission(s) will remain in Standard Access until your request has been reviewed and approved.

[Permalink](#faq_243889534743436)

[How long does it take to get the results of my submission?](#faq_129423573421020)

For apps requiring access to use cases, permissions or features (for some apps this is called [advanced access](/docs/graph-api/overview/access-levels/#advanced-access)): Your submission will be evaluated immediately and it may take up to 30 seconds to receive results. If you receive an error, or you do not see a confirmation message after submitting, please click the Submit button on the form again to re-submit the form. Your responses will be saved in the form if this happens.

For apps that have been published live with a use case, or that have [advanced access](/docs/graph-api/overview/access-levels/#advanced-access) to permissions or features: Your submission will be evaluated within a few days. You will receive a message in an email and your Alerts Inbox.

[Permalink](#faq_129423573421020)

[How will I know the status of my Advanced Access request?](#faq_1249615725623850)

On your permissions and features dashboard, you can check the status of your request. The Access Level will change to “Advanced Access” once your request has been reviewed and approved.

[Permalink](#faq_1249615725623850)

[How will I know the status of my Data Use Checkup?](#faq_346625191578639)

You can check the status of DUC on your Apps Dashboard.

[Permalink](#faq_346625191578639)

[Can I create an app if my answers to data handling questions are not approved?](#faq_814491204031004)

If your answers to data handling questions are not approved, your app will remain in development mode with standard access to permissions and features.

[Permalink](#faq_814491204031004)

[I was not granted access to the use case or permission(s) I requested, what can I do?](#faq_8953855498019621)

* In order to gain advanced access to the permission(s), you will need to implement additional protections. Please see our [Data Handling Guidelines](/docs/development/release/data-handling-questions/best-practices) for more information.
* Please also review the [Business Verification](/docs/development/release/business-verification) process and ensure your app is connected to a verified business. All apps requesting Advanced Access to new permissions must have their business verified.
* Additionally, please review our [App Review](/docs/app-review) process which is required when you request access to most permissions

[Permalink](#faq_8953855498019621)

[If changes to my data handling practices are required, can I re-submit my answers to the data handling questions?](#faq_1378042726163603)

Yes, you can re-submit your answers. If your answers are found to be insufficient 3 consecutive times, you must wait 3 calendar days from your last denied submission before trying again.

[Permalink](#faq_1378042726163603)

[If my request for a use case or access to permission(s) was not granted, will my previous answers be saved?](#faq_297764356625274)

Yes, your previous answers are auto-saved. If your request was not granted, it will reload the previous auto-saved state when you return to edit your responses when you submit your request again.

[Permalink](#faq_297764356625274)

[How often will I need to answer and submit the data handling questions?](#faq_784083163773600)

You will be prompted to answer questions about data handling whenever you request a use case or permissions and features (for some this is called advanced access. Additionally, if you have apps that have been published live with a use case, or that have [advanced access](/docs/graph-api/overview/access-levels/#advanced-access) to permissions or features, you are required to answer data handling questions during your annual Data Use Checkup.

[Permalink](#faq_784083163773600)
