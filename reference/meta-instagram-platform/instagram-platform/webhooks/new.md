# "Instagram Post Shares: New Attachment Type and Transition Period"



Starting November 3, 2025, the webhook payload for Instagram post shares will include two attachments: the existing `share` attachment and a new `ig_post` attachment. The payload now provides additional metadata, including media ID, URL, and title (caption).

If this change is not compatible with your app and you need more time to make updates, please contact our BSE support team via the [Meta Developer Support Portal](https://developers.facebook.com/support/) to request exclusion of your app(s) from this change until you make the necessary updates to support the new attachment type.

The old `share` attachment type will continue to be supported for Instagram posts until **February 1, 2026**, after which it will be removed. Partners and integrators are encouraged to migrate to the new `ig_post` attachment type as soon as possible.

### Previous Payload

```curl
{
  "object": "instagram",
  "entry": [
    {
      "time": 1761287298065,
      "id": "{PAGE_ID}",
      "messaging": [
        {
          "sender": {
            "id": "{SENDER_ID}"
          },
          "recipient": {
            "id": "{PAGE_ID}"
          },
          "timestamp": 1761287294014,
          "message": {
            "mid": "{MESSAGE_ID}",
            "attachments": [
              {
                "type": "share",
                "payload": {
                  "ig_post_media_id": "18139494541428835",
                  "title": "Build a workspace that attracts talent and supports your team with solutions made for growing businesses.",
                  "url": "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=18139494541428835={SIGNATURE}"
                }
              }
            ]
          }
        }
      ]
    }
  ]
}
```

### New Sample Webhook Payload

```curl
{
  "object": "instagram",
  "entry": [
    {
      "time": 1761287298065,
      "id": "{PAGE_ID}",
      "messaging": [
        {
          "sender": {
            "id": "{SENDER_ID}"
          },
          "recipient": {
            "id": "{PAGE_ID}"
          },
          "timestamp": 1761287294014,
          "message": {
            "mid": "{MESSAGE_ID}",
            "attachments": [
              {
                "type": "share",
                "payload": {
                  "ig_post_media_id": "18139494541428835",
                  "title": "Build a workspace that attracts talent and supports your team with solutions made for growing businesses.",
               "url": "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=18139494541428835={SIGNATURE}"
                }
              },
              {
                "type": "ig_post",
                "payload": {
                  "ig_post_media_id": "18139494541428835",
                  "title": "Build a workspace that attracts talent and supports your team with solutions made for growing businesses.",
                  "url": "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=18139494541428835={SIGNATURE}"
                }
              }
            ]
          }
        }
      ]
    }
  ]
}
```
