# &quot;Instagram Post Shares: New Attachment Type and Transition Period&quot;



Starting November 3, 2025, the webhook payload for Instagram post shares will include two attachments: the existing `share` attachment and a new `ig_post` attachment. The payload now provides additional metadata, including media ID, URL, and title (caption).

If this change is not compatible with your app and you need more time to make updates, please contact our BSE support team via the [Meta Developer Support Portal](https://developers.facebook.com/support/) to request exclusion of your app(s) from this change until you make the necessary updates to support the new attachment type.

The old `share` attachment type will continue to be supported for Instagram posts until **February 1, 2026**, after which it will be removed. Partners and integrators are encouraged to migrate to the new `ig_post` attachment type as soon as possible.

### Previous Payload

```curl
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;time&quot;: 1761287298065,
      &quot;id&quot;: &quot;&#123;PAGE_ID&#125;&quot;,
      &quot;messaging&quot;: [
        &#123;
          &quot;sender&quot;: &#123;
            &quot;id&quot;: &quot;&#123;SENDER_ID&#125;&quot;
          &#125;,
          &quot;recipient&quot;: &#123;
            &quot;id&quot;: &quot;&#123;PAGE_ID&#125;&quot;
          &#125;,
          &quot;timestamp&quot;: 1761287294014,
          &quot;message&quot;: &#123;
            &quot;mid&quot;: &quot;&#123;MESSAGE_ID&#125;&quot;,
            &quot;attachments&quot;: [
              &#123;
                &quot;type&quot;: &quot;share&quot;,
                &quot;payload&quot;: &#123;
                  &quot;ig_post_media_id&quot;: &quot;18139494541428835&quot;,
                  &quot;title&quot;: &quot;Build a workspace that attracts talent and supports your team with solutions made for growing businesses.&quot;,
                  &quot;url&quot;: &quot;https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=18139494541428835=&#123;SIGNATURE&#125;&quot;
                &#125;
              &#125;
            ]
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

### New Sample Webhook Payload

```curl
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;time&quot;: 1761287298065,
      &quot;id&quot;: &quot;&#123;PAGE_ID&#125;&quot;,
      &quot;messaging&quot;: [
        &#123;
          &quot;sender&quot;: &#123;
            &quot;id&quot;: &quot;&#123;SENDER_ID&#125;&quot;
          &#125;,
          &quot;recipient&quot;: &#123;
            &quot;id&quot;: &quot;&#123;PAGE_ID&#125;&quot;
          &#125;,
          &quot;timestamp&quot;: 1761287294014,
          &quot;message&quot;: &#123;
            &quot;mid&quot;: &quot;&#123;MESSAGE_ID&#125;&quot;,
            &quot;attachments&quot;: [
              &#123;
                &quot;type&quot;: &quot;share&quot;,
                &quot;payload&quot;: &#123;
                  &quot;ig_post_media_id&quot;: &quot;18139494541428835&quot;,
                  &quot;title&quot;: &quot;Build a workspace that attracts talent and supports your team with solutions made for growing businesses.&quot;,
               &quot;url&quot;: &quot;https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=18139494541428835=&#123;SIGNATURE&#125;&quot;
                &#125;
              &#125;,
              &#123;
                &quot;type&quot;: &quot;ig_post&quot;,
                &quot;payload&quot;: &#123;
                  &quot;ig_post_media_id&quot;: &quot;18139494541428835&quot;,
                  &quot;title&quot;: &quot;Build a workspace that attracts talent and supports your team with solutions made for growing businesses.&quot;,
                  &quot;url&quot;: &quot;https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=18139494541428835=&#123;SIGNATURE&#125;&quot;
                &#125;
              &#125;
            ]
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```
