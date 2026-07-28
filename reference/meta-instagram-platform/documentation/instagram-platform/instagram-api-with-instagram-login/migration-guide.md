# Migrate your App



This guide will help you determine whether you should migrate your existing app to the new Instagram product and how to implement it.

## Why migrate your app

The Instagram API with Instagram Login offers a streamlined and efficient way for your app users to manage their Instagram professional accounts without the need for a Facebook Page or Facebook presence. With only two permissions required for each functionality – `instagram_business_basic` and the permission specific to messaging, comment moderation, or content publishing – the onboarding process has been significantly simplified, going from an average of 12 steps to just two. As a result, we&#039;ve seen a significant improvement in onboarding success rates.

## Should you migrate your app

Use the following table to determine if you should implement the Instagram product into your app:

| Component | [Instagram API setup with Instagram Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login) | [Instagram API setup with Facebook Login](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login) |
| --- | --- | --- |
| **Access token type** | Instagram User | Facebook User or Page |
| **Authorization type&lt;br&gt;** | [Business Login for Instagram](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login) | [Facebook Login for Business](https://developers.facebook.com/documentation/facebook-login/facebook-login-for-business) |
| **Comment moderation&lt;br&gt;** | ✅ | ✅ |
| **Content publishing&lt;br&gt;** | ✅ | ✅ |
| **Facebook Page&lt;br&gt;** | x | Required |
| **Hashtag search** | x | ✅ |
| [**Insights&lt;br&gt;**](https://developers.facebook.com/documentation/instagram-platform/insights) | ✅ | ✅ |
| **Mentions&lt;br&gt;** | ✅ | ✅ |
| **Messaging ** | ✅ | [via Messenger Platform](https://developers.facebook.com/documentation/business-messaging/instagram-messaging) |
| [**Product tagging&lt;br&gt;**](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging) | x | ✅ |
| [**Partnership Ads&lt;br&gt;**](https://developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/partnership-ads) | x | ✅ |

## Migration Steps

You will need to take the following steps to migrate your app.

### Step 1. Add Instagram

Follow the [Create a Meta app with Instagram guide](https://developers.facebook.com/documentation/instagram-platform/create-an-instagram-app) to add the Instagram product to your existing business type app.

**Warning:** If your current Meta app type is **not** a Business type app you will need to create a new app and [select **Business** during the creation process.](https://developers.facebook.com/documentation/instagram-platform/create-an-instagram-app#step-4--select-your-app-type)

If this new app needs Advanced Access, [App Review](https://developers.facebook.com/documentation/instagram-platform/create-an-instagram-app#step-10--complete-app-review)  is required and will be handled within the Instagram product flow instead of the App Review item in the left side dashboard menu.

You will configure:

* Instagram Login for Business
* Permissions and features
* Webhooks

### Step 2. Update your code

1. Copy and paste the **Embed URL** in an anchor tag or button on your app or website to launch the Business Login for Instagram flow. This flow will give your app an Instagram User access token.
4. Update the host URL in your code so that your API calls use `graph.instagram.com`.
5. Update your API calls to use an Instagram User access token. This will update the `/me` endpoint calls to use an Instagram Professional account ID instead of a Facebook Page ID
6. Replace your Meta app ID and app secret with the Instagram app ID and secret found in the app dashboard; **Instagram &gt; API setup with Instagram login &gt; 3. Set up Instagram business login &gt; Business login settings**.
