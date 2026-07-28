# Webhook debugger



Use the Instagram Messaging Webhook Debugger to check if your app has the correct subscriptions and permissions for pages that your app is connected to as part of your IG Messaging API integrations. Access it from **Developer app dashboard → Messenger → Instagram Settings**. It is only available for users who have an **Administrator** [role](https://developers.facebook.com/docs/development/build-and-test/app-roles) on your app.

## Requirements
* Tool is only accessible to users with Administrator [role](https://developers.facebook.com/docs/development/build-and-test/app-roles) on your app.
* Tool only works for pages/handle that are connected to your app.
* Ensure that you have an Instagram account and it is linked to your Facebook account (needed so that the debug webhook will be sent with your details rather than a random user)
* Do not use the tool to run random checks as it will add to your API call rates. Only use it to debug if you have an actual issue.

## How to use

### Check subscriptions and setup

1. Go to the [Meta App Dashboard](https://developers.facebook.com/apps) and select your app.
2. Navigate to **App Dashboard → Messenger → Instagram Settings** and scroll to the bottom to see the Webhook debugger section.
3. Enter Page ID of Facebook Page connected to the Instagram account that you want to check. Click **Submit**.
4. The tool shows details like webhook subscriptions, connected Instagram account, and Messaging toggle status.
5. If any of them is incorrect or missing, the tool shows it in red with detail links to fix those.

### Send debug webhook

If the setup is correct but your app is still not receiving webhooks, follow the steps listed.

1. Navigate to the Send debug webhook section and enter the Page ID (connected to the IG account) for which you are not receiving webhooks.
2. Click **Submit**.
3. If all setup is correct, then a sample messages webhook will be sent to your app.
4. A TraceID will also be shown like in the screenshot below.
5. If your app still does not receive the sample webhook, please share the TraceID in a ticket via our support platform, detailing the steps you followed and any additional context.
