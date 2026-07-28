# Getting Started



This document explains how to successfully call the Instagram API with Facebook Login for Business with your app and get an Instagram Business or Creator Account's media objects. It assumes you are familiar with and how to perform REST API calls. If you do not have an app yet, you can use the [Graph API Explorer](https://developers.facebook.com/tools/explorer) instead and skip steps 1 and 2.  

## Before You Start

You will need access to the following:

- An [Instagram Business Account](https://help.instagram.com/502981923235522) or [Instagram Creator Account](https://help.instagram.com/1158274571010880)
- A [Facebook Page connected to that account](https://developers.facebook.com/documentation/instagram-platform/overview#pages)
- A Facebook Developer account that can perform [Tasks on that Page](https://developers.facebook.com/documentation/instagram-platform/overview#tasks)
- A [registered Facebook App](https://developers.facebook.com/documentation/development/register) with **Basic** settings configured

## 1. Configure Facebook Login for Business

Add the Facebook Login product to your app in the App Dashboard.

You can leave all settings on their defaults. If you are implementing Facebook Login for Business manually (which we don't recommend), enter your `redirect_uri` in the **Valid OAuth redirect URIs** field. If you will be using one of our SDKs, you can leave it blank.

## 2. Implement Facebook Login for Business

Follow our [Facebook Login for Business documentation](https://developers.facebook.com/docs/facebook-login-for-business) for your platform and implement the login into your app. Set up your implementation to request these permissions:

- [`instagram_basic`](https://developers.facebook.com/docs/apps/review/login-permissions#instagram-basic)
- [`pages_show_list`](https://developers.facebook.com/docs/apps/review/login-permissions#pages-show-list)

## 3. Get a User Access Token

Once you've implemented Facebook Login for Business, make sure you are signed into your Facebook Developer account, then access your app and trigger the Facebook Login for Business modal. Remember, your Facebook Developer account must be able to perform [Tasks](https://developers.facebook.com/documentation/instagram-platform/overview#tasks) on the [Facebook Page](https://developers.facebook.com/documentation/instagram-platform/overview#pages) connected to the Instagram account you want to query.

Once you have triggered the modal, click **OK** to grant your app the `instagram_basic` and `pages_show_list` permissions.

The API should return a User access token. Capture the token so your app can use it in the next few queries. If you are using the Graph API Explorer, it will be captured automatically and displayed in the **Access Token** field for reference:

## 4. Get the User's Pages

Query the `GET /me/accounts` endpoint (this translates to `GET /{user-id}/accounts`, which perform a `GET` on the Facebook [User](https://developers.facebook.com/docs/graph-api/reference/user) node, based on your access token).

```curl
curl -i -X GET \
 "https://graph.facebook.com/v25.0/me/accounts?access_token={access-token}"
```

This should return a collection of Facebook Pages that the current Facebook User can perform the `MANAGE`, `CREATE_CONTENT`, `MODERATE`, or `ADVERTISE` tasks on:

```json
{
  "data": [
    {
      "access_token": "EAAJjmJ...",
      "category": "App Page",
      "category_list": [
        {
          "id": "2301",
          "name": "App Page"
        }
      ],
      "name": "Metricsaurus",
      "id": "134895793791914",  // capture the Page ID
      "tasks": [
        "ANALYZE",
        "ADVERTISE",
        "MODERATE",
        "CREATE_CONTENT",
        "MANAGE"
      ]
    }
  ]
}
```

Capture the ID of the Facebook Page that's connected to the Instagram account that you want to query. Keep in mind that your app users may be able to perform tasks on multiple pages, so you eventually will have to introduce logic that can determine the correct Page ID to capture (or devise a UI where your app users can identify the correct Page for you).

## 5. Get the Page's Instagram Business Account

Use the Page ID you captured to query the `GET /{page-id}?fields=instagram_business_account` endpoint:

```curl
curl -i -X GET \
 "https://graph.facebook.com/v25.0/134895793791914?fields=instagram_business_account&access_token={access-token}"
```

This should return the [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) — an Instagram Business or Creator Account — that's connected to the Facebook Page.

```json
{
  "instagram_business_account": {
    "id": "17841405822304914"  // Connected IG User ID
  },
  "id": "134895793791914"  // Facebook Page ID
}
```

Capture the [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) ID.

## 6. Get the Instagram Business Account's Media Objects

Use the [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) ID you captured to query the `GET /{ig-user-id}/media` endpoint:

```curl
curl -i -X GET \
 "https://graph.facebook.com/v25.0/17841405822304914/media?access_token={access-token}"
```

This should return the IDs of all the [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects on the [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user):

```json
{
  "data": [
    {
      "id": "17918195224117851"
    },
    {
      "id": "17895695668004550"
    },
    {
      "id": "17899305451014820"
    },
    {
      "id": "17896450804038745"
    },
    {
      "id": "17881042411086627"
    },
    {
      "id": "17869102915168123"
    }
  ],
  "paging": {
    "cursors": {
      "before": "QVFIUkdGRXA2eHNNTUs4T1ZAXNGFxQTAtd3U4QjBLd1B2NXRMM1NkcnhqRFdBcEUzSDVJZATFoLWtXMWZAGU2VrRTk2RHVtTVlDckI2NjN0UERFa2JrUk4yMW13",
      "after": "QVFIUmlwbnFsM3N2cV9lZAFdCa0hDeV9qMVliT0VuMmJyNENxZA180c0t6VjFQVEJaTE9XV085aU92OUFLNFB6Szd2amo5aV9rTlVBcnNlWmEtMzYxcE1HSFR3"
    }
  }
}
```

If you are able to perform this final query successfully, you should be able to perform queries using any of the Instagram Platform endpoints — just refer to our various guides and references to learn what each endpoint can do and what permissions they require.

## Next Steps

- Develop your app further so it can successfully use any other endpoints it needs, and keep track of the permissions each endpoint requires
    - If you plan to implement [Instagram Messaging from Messenger Platform](https://developers.facebook.com/documentation/business-messaging/instagram-messaging) you will need additional permissions
- Complete the [App Review](https://developers.facebook.com/documentation/instagram-platform/overview#app-review) process and request approval for all of the permissions your app will need so your app users can grant them while your app is in [Live Mode](https://developers.facebook.com/documentation/development/build-and-test/app-modes#live-mode)
- Switch your app to Live Mode and market it to potential users  

Once your app is in Live Mode, any Facebook User who you've made your app available to can access an Instagram Business or Creator Account's data, as long as they have a Facebook User account that can perform Tasks on the Page connected to that Instagram Business or Creator Account.
