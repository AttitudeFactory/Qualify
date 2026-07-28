# Facebook Login Overview


**Warning:** If you want to log into Facebook, go to [http://www.facebook.com](http://www.facebook.com). If you are having trouble logging into Facebook, visit our [Help Center](https://www.facebook.com/help/1573156092981768/).

Facebook Login is a fast and convenient way for people to create accounts and log into your app across multiple platforms. It&#039;s available on [iOS](https://developers.facebook.com/documentation/facebook-login/ios), [Android](https://developers.facebook.com/documentation/facebook-login/android), [Web](https://developers.facebook.com/documentation/facebook-login/web), [desktop apps](https://developers.facebook.com/documentation/facebook-login/guides/advanced/manual-flow) and [devices such as Smart TVs and Internet of Things objects](https://developers.facebook.com/documentation/facebook-login/for-devices). Facebook Login enables two scenarios, [authentication](https://developers.facebook.com/documentation/facebook-login/auth-vs-data#authentication) and asking for [permissions](https://developers.facebook.com/documentation/facebook-login/guides/permissions) to [access people&#039;s data](https://developers.facebook.com/documentation/facebook-login/auth-vs-data#data-access). You can use Facebook Login simply for authentication or for both authentication and data access.

## Use Cases
Facebook Login is used to enable the following experiences:

- **Account Creation**

Facebook Login lets people quickly and easily create an account in your app without having to set (and likely later forget) a password. This simple and convenient experience leads to higher conversion. Once someone has created an account on one platform, they can log into your app—often with a single click—on all your other platforms. A validated email address means you&#039;re able to reach that person to re-engage them at a later date.

- **Personalization**

Personalized experiences are more engaging and lead to higher retention. Facebook Login lets you access information which would be complex or arduous to collect via your own registration form.  Even just importing someone&#039;s profile picture from Facebook gives them a stronger sense of connection with your app.

## Success Stories

Developers who have implemented Facebook Login in their apps have seen dramatic increases in logins, higher levels of engagement, and continuing increases in the number of people using Facebook Login. For details, see [Success Stories](https://developers.facebook.com/success-stories).

For example, [Skyscanner](https://developers.facebook.com/success-stories/skyscanner), an app for finding flights, hotels, and car rentals, has experienced a 100% increase in the number of people using Facebook Login to access the app.

## Features &#123;#features&#125;

- **Real Identity**

When people choose to log in with Facebook, they can share their real identity through their public profile. Public Profile includes a person&#039;s real name and a profile picture. Apps based on real identity often have less spam and foster higher quality conversations.

- **Cross Platform Login**

Facebook Login is available on the most common mobile and desktop app platforms. People who create accounts with Facebook on one platform can quickly and easily log into your app on another. A person is known by the same User ID everywhere so they can pickup your in-app experience where they left off. Facebook Login is available on [iOS](https://developers.facebook.com/documentation/facebook-login/ios), [Android](https://developers.facebook.com/documentation/facebook-login/android), and [Web](https://developers.facebook.com/documentation/facebook-login/web), for [desktop apps](https://developers.facebook.com/documentation/facebook-login/guides/advanced/manual-flow) and for [devices such as Smart TVs and Internet of Things objects](https://developers.facebook.com/documentation/facebook-login/for-devices)

- **Works Alongside Your Existing Account System**

Facebook Login complements your existing account system. Give people the option to log in with Facebook alongside email, SMS, or other social login choices. Where an email address you get from Facebook Login matches one already in your system, you can log that person into their existing account without additional passwords.

- **Granular Permissions**

Facebook Login supports [many permissions](https://developers.facebook.com/docs/facebook-login/permissions) which determine which information people choose to share with your app. This means you have precise control over what you request and people have precise control over what they choose to approve.

- **People Have Control Over What They Share**

Great experiences start by giving people control. With Facebook Login, people can choose which information they share with your app. They can still get the benefits of logging in with Facebook even if they feel uncomfortable granting access to certain information. Your app can later re-request this information once you&#039;ve explained how the person&#039;s experience will be enhanced.

- **Gradual Authorization**

Facebook Login supports the gradual authorization—you don&#039;t have to request all the information you want up front—you can do it over time. This means people can quickly and easily create accounts in your app—and as their experience with your app deepens, you can request addition information to further enhance their experience.

- **Express Login**

Express Login helps users log in with their Facebook account across devices and platforms. If a person has logged into your app before on any platform, you can use Express Login to log them in with their Facebook account on Android, instead of asking for them to select a login method, which sometimes resulted in creating duplicate accounts or even failing to log in at all.

- **Facebook Lite Integration for Android Apps**

When you develop your app with version 4.14.0 of the Facebook SDK for Android, Facebook Login has automatic integration with Facebook Lite. If people don&#039;t have the Facebook Android app installed, Facebook Login uses Facebook Lite instead to display the login screen and get credentials. Previous SDKs required that people have the Facebook app installed.

## App Review &#123;#review&#125;

We want to ensure the tens of millions of people who use Facebook Login every day have a safe, reliable and consistent experience. App Review helps determine if apps that are requesting access to detailed account information have built great experiences.

Our App Review process is designed to be fast and lightweight. Our review team actually uses your app and will provide guidance and feedback to ensure you&#039;re meeting our [Facebook Platform Terms](https://developers.facebook.com/terms) and [Developer Policies](https://developers.facebook.com/devpolicy).

Apps may ask for the following two permissions from any person **without** submitting for review by Facebook:

* [`public profile`](https://developers.facebook.com/docs/facebook-login/permissions#reference-public-profile)
* [`email`](https://developers.facebook.com/docs/facebook-login/permissions#reference-email)

To ask for any other permission, your app will need to be [reviewed by Facebook](https://developers.facebook.com/docs/facebook-login/review) before these permission become visible in the Login Dialog to the public who&#039;re logging into your app with Facebook.

However, to help you develop your Facebook Login experience, anyone listed in the Roles section of your app&#039;s dashboard will be able to grant any valid [permission](https://developers.facebook.com/docs/facebook-login/permissions) without approval from Facebook. For information about roles and permissions, see [Access Levels](https://developers.facebook.com/docs/graph-api/overview/access-levels).

Learn more about [App Review](https://developers.facebook.com/docs/facebook-login/review).

## Data Deletion &#123;#data-deletion&#125;

As part of compliance with General Data Protection Regulation (GDPR), Facebook gives people control of their data by providing a way for people to request your app to delete the data it has from Facebook about them. To respond to such a request, implement a [data deletion callback](https://developers.facebook.com/docs/apps/delete-data).

To be compliant with [GDPR guidelines](https://ico.org.uk/for-organisations/guide-to-data-protection/guide-to-the-general-data-protection-regulation-gdpr/individual-rights/right-to-erasure/), you must provide the following:

* A way in your app for users to request their data be deleted

* A contact email address that people can use to reach you to request their data be deleted

* An implementation of the data [deletion callback](https://developers.facebook.com/docs/apps/delete-data)

After removing an app from the **Apps and Websites** settings page, a user should see the option of requesting the app delete their data by either following a link to instructions on how to request their data be deleted or by a data deletion request. This replaces the current experience that links to the app’s privacy policy.

Developers can provide both the data deletion callback and a link to instructions for how users can delete their data.

## Start Building &#123;#get-started&#125;

+ [For iOS Apps](https://developers.facebook.com/documentation/facebook-login/ios)
+ [For Android Apps](https://developers.facebook.com/documentation/facebook-login/android)
+ [For Web and Mobile Web Apps](https://developers.facebook.com/documentation/facebook-login/web)
+ [For Desktop Apps](https://developers.facebook.com/documentation/facebook-login/guides/advanced/manual-flow)
+ [For Smart Devices](https://developers.facebook.com/documentation/facebook-login/for-devices) (Smart TVs and Internet of Things objects)

## Learn More &#123;#learn-more&#125;

+ [Permissions](https://developers.facebook.com/docs/facebook-login/permissions)
+ [Access Tokens](https://developers.facebook.com/documentation/facebook-login/guides/access-tokens)
+ [App Review for Login](https://developers.facebook.com/docs/facebook-login/review)
+ [Security](https://developers.facebook.com/documentation/facebook-login/security)
+ [APIs and SDKs](https://developers.facebook.com/docs#apis-and-sdks)
