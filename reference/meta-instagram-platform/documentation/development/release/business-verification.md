# Business Verification



**Note:** **[Advanced Access](https://developers.facebook.com/docs/graph-api/overview/access-levels#advanced-access) now requires Business Verification.**

As of February 1, 2023, if your app requires advanced level access to permissions, you might need to complete [Business Verification](https://developers.facebook.com/documentation/development/release/business-verification). [See this blog post for more information.](https://developers.facebook.com/blog/post/2023/02/01/developer-platform-requiring-business-verification-for-advanced-access/)

Business Verification is a process that allows us to gather information about you and your Business so we can verify your identity as a business entity.

Apps that request [advanced access](https://developers.facebook.com/docs/graph-api/overview/access-levels#advanced-access) for permissions and apps that allow other [Businesses](https://business.facebook.com/) to access their own data must be connected to a Business that has completed Business Verification. Until then, app users from other Businesses will be unable to grant these apps [permissions](https://developers.facebook.com/docs/permissions/reference) and all [features](https://developers.facebook.com/docs/apps/features-reference) will be inactive.

If your app will only be used by app users who have a [role](https://developers.facebook.com/documentation/development/build-and-test/app-roles) on the app itself you do not need to complete verification; these users can grant your app any permissions at any time and all features are always active.

You can use the App Dashboard to connect your app to a Business that you&#039;re an Admin of, regardless of whether or not the Business has been verified, but the verification process itself must be completed in the Facebook Business Manager. If you do not have a Business, you will be given the option to create one.

Note that anyone with an Administrator role on your app can connect it to a Business, but only someone with an Admin role in the Business will be able to complete the verification process.

## Step 1: Connect your app to a Business

Load your app in the App Dashboard and go to **Settings** &gt; **Basic** &gt; **Verification** and click the Start Verification button or the **+ Business Verification** link if you have previously completed Individual Verification.

If your Facebook developer account is already associated with a Facebook Business account, you will be given the option to select a Business within it:

If you don&#039;t have a Facebook Business account, or if your account contains no Businesses, you will be prompted to create one.

Connecting your app to a verified Business completes the connection process and there&#039;s nothing else you have to do. The **Verification** section should show that your app is now connected to a verified Business:

If, however, you connected your app to an unverified Business, you must complete the verification process in the Business Manager.

## Step 2: Verify your Business

If you connected your app to an unverified Business, you or Admin of the Business must complete the verification process within the Business Manager.

Click Start Business Verification to load the unverified Business in the Business Manager and complete the verification process.

Refer to our Business Manager Help Center&#039;s [About Business Verification](https://www.facebook.com/business/help/1095661473946872) topic for an explanation of the process and a list of documents you will need.

Once you have completed verification, return to the Basic Settings panel. You should see that your app is now connected to a verified Business:

