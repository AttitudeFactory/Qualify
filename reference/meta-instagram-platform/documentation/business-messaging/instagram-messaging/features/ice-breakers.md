# Ice Breakers



Ice Breakers provide a way for users to start a conversation with a business with a list of frequently asked questions. Use the Ice Breaker API to set a maximum of 4 questions.

## Limitations

Ice Breakers are currently not available on desktop.

## Setting ice breakers

```curl
    curl -X POST -H &quot;Content-Type: application/json&quot; -d &#039;&#123;
     &quot;platform&quot;: &quot;instagram&quot;,
     &quot;ice_breakers&quot;:[
       &#123;
          &quot;call_to_actions&quot;:[
             &#123;
                &quot;question&quot;:&quot;&lt;QUESTION&gt;&quot;,
                &quot;payload&quot;:&quot;&lt;PAYLOAD&gt;&quot;
             &#125;,
             &#123;
                &quot;question&quot;:&quot;&lt;QUESTION&gt;&quot;,
                &quot;payload&quot;:&quot;&lt;PAYLOAD&gt;&quot;
             &#125;
          ],
          &quot;locale&quot;:&quot;default&quot; // default locale is REQUIRED
       &#125;,
       &#123;
          &quot;call_to_actions&quot;:[
             &#123;
                &quot;question&quot;:&quot;&lt;QUESTION&gt;&quot;,
                &quot;payload&quot;:&quot;&lt;PAYLOAD&gt;&quot;
             &#125;,
             &#123;
                &quot;question&quot;:&quot;&lt;QUESTION&gt;&quot;,
                &quot;payload&quot;:&quot;&lt;PAYLOAD&gt;&quot;
             &#125;
          ],
          &quot;locale&quot;:&quot;en_GB&quot;
       &#125;
    ]
&#125;&#039; &quot;https://graph.facebook.com/v11.0/me/messenger_profile?platform=instagram&amp;access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot;
```

## Getting ice breakers

```curl
curl -X GET &quot;https://graph.facebook.com/v11.0/me/messenger_profile?fields=ice_breakers&amp;platform=instagram&amp;access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot;
```

```curl
&#123;
   &quot;data&quot;: [
        &#123;
          &quot;call_to_actions&quot; : [
               &#123;
                &quot;question&quot;: &quot;&lt;QUESTION&gt;&quot;,
                &quot;payload&quot;: &quot;&lt;PAYLOAD&gt;&quot;,

               &#125;,
               &#123;
                &quot;question&quot;: &quot;&lt;QUESTION&gt;&quot;,
                &quot;payload&quot;: &quot;&lt;PAYLOAD&gt;&quot;,

               &#125;,
          ],
          &quot;locale&quot;: &quot;&lt;LOCALE&gt;&quot;,
      &#125;,
      &#123;
          &quot;call_to_actions&quot; : [
               &#123;
                &quot;question&quot;: &quot;&lt;QUESTION&gt;&quot;,
                &quot;payload&quot;: &quot;&lt;PAYLOAD&gt;&quot;,

               &#125;,
               &#123;
                &quot;question&quot;: &quot;&lt;QUESTION&gt;&quot;,
                &quot;payload&quot;: &quot;&lt;PAYLOAD&gt;&quot;,

               &#125;,
          ],
          &quot;locale&quot;: &quot;&lt;LOCALE&gt;&quot;,
      &#125;
   ]
&#125;
```

## Deleting ice breakers

```curl
curl -X DELETE -H &quot;Content-Type: application/json&quot; -d &#039;&#123;
  &quot;fields&quot;: [
    &quot;ice_breakers&quot;,
  ]
&#125;&#039; &quot;https://graph.facebook.com/v11.0/me/messenger_profile?platform=instagram&amp;access_token=%lt;PAGE_ACCESS_TOKEN&gt;&quot;
```

## Webhook event

To receive postback webhooks from Ice Breakers, subscribe your app to the `messaging_postbacks` webhook under the Instagram topic in your app settings.

The webhook will receive a JSON payload similar to the example below.

```
&#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;&lt;IGID&gt;&quot;,
      &quot;time&quot;: 1502905976963,
      &quot;messaging&quot;: [
        &#123;
          &quot;sender&quot;: &#123;
            &quot;id&quot;: &quot;&lt;IGSID&gt;&quot;
          &#125;,
          &quot;recipient&quot;: &#123;
            &quot;id&quot;: &quot;&lt;IGID&gt;&quot;
          &#125;,
          &quot;timestamp&quot;: 1502905976377,
          &quot;postback&quot;: &#123;
            &quot;title&quot;: &quot;&lt;SELECTED_ICEBREAKER_QUESTION&gt;&quot;,
            &quot;payload&quot;: &quot;&lt;USER_DEFINED_PAYLOAD&gt;&quot;,
          &#125;
        &#125;
      ]
    &#125;
  ]
&#125;
```

### Developer Support

* Use the  [Meta Status tool](https://metastatus.com) to check for the status and outages of Meta business products.
* Use the [Meta Developer Support tool](https://developers.facebook.com/support) to report bugs and view reported bugs, get help with Ads or Business Manager, and more.

