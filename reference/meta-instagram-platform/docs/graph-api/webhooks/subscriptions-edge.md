# Subscriptions Edge

You can use the Graph API's `/app/subscriptions` edge to configure and manage your app's Webhooks product. Refer to our [/app/subscriptions documentation](/docs/graph-api/reference/app/subscriptions) to see which operations you can perform with this edge, and any permissions they require. This document only covers a few common operations.

## Creating Subscriptions

To subscribe to an object and its fields, send a `POST` request to the [/app/subscriptions edge](/docs/graph-api/reference/app/subscriptions) and include the following parameters:

* `object` — The type of object you want to set up field subscriptions for (e.g., `user`).
* `callback_url` — Your endpoint's URL.
* `verify_token` — A `string` that we will include whenever we send you a [verification request](/docs/graph-api/webhooks/getting-started#verification-requests).
* `fields` — The fields you want to subscribe to (e.g., `photos`).

For example, if your app's ID were `188559381496048` and you want to be notified when your app's user publish a new photo, you could do this:

#### Sample Request

```
curl -F "object=user" \
     -F "callback_url=https://your-clever-domain-name.com/webhooks" \
     -F "fields=photos" \
     -F "verify_token=your-verify-token" \
     -F "access_token=your-app-access-token" \
     "https://graph.facebook.com/188559381496048/subscriptions"
```

#### Sample Response

If successful:

```
{
  "success": "true"
}
```

## Getting Subscription Information

To see the object and field subscriptions that you have set up for your app, send a `GET` request the `/app/subscriptions` edge. For example, if your app's ID were `188559381496048`, you could do this:

#### Sample Request

```
GET graph.facebook.com/188559381496048/subscriptions
```

#### Sample Response

```
{
  "data": [
    {
      "object": "user",
      "callback_url": "https://your-clever-domain-name.com/webhooks",
      "active": true,
      "fields": [
        {
          "name": "photos",
          "version": "v2.10"
        },
        {
          "name": "feed",
          "version": "v2.10"
        }
      ]
    }
  ]
}
```
