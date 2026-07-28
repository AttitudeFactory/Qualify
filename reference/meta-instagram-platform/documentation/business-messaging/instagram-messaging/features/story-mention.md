# Story Mention



Instagram notifies an Instagram Professional account when a user mentions it in a story. When this happens, the IG Professional account gets a message in the inbox referencing the story that the user posted. Because a story is temporary (it disappears after 24 hours or when deleted by the user), you must meet specific requirements and implementation guidelines to comply and respect user privacy for ephemeral content.

## Important points

* A story mention webhook will only flow in if the user mentioning the account has their account set up as public. Story mentions from a private account will only flow in if the account follows the said account.
* You must not store or cache the media content on your server.

## Developer implementation flow
* You get a webhook for every story mention received with the story CDN URL. You can store the CDN URL on your system to avoid repeated calls to conversation API. You must not store the media content on your server.
* When the agent clicks on the content or opens the thread, it will trigger a call to your server.
* The agent&#039;s browser renders the content using the CDN URL obtained via webhooks/Conversation API.
* Once the user deletes the story or it expires, the URL will stop rendering and you should show a placeholder message indicating that the story content is no longer available.

## Rendering story in agent&#039;s inbox/client view

There are several options where you can choose to render the story content in the agent&#039;s inbox:

* *In-thread rendering* - For this scenario/behavior, when the agent clicks a particular thread, you will load the CDN URL and render it on the client&#039;s side.
* *User action rendering* - For this scenario/behavior, the client renders story content with a placeholder, and when the user clicks the display/view button, you will load the CDN URL and render it on the client&#039;s side.

## Example webhook

```json
  &#123;
  &quot;object&quot;: &quot;instagram&quot;,
  &quot;entry&quot;: [
    &#123;
      &quot;id&quot;: &quot;&lt;IGID&gt;&quot;,
      &quot;time&quot;: 1569262486134,
      &quot;messaging&quot;: [
        &#123;
          &quot;sender&quot;: &#123;
            &quot;id&quot;: &quot;&lt;IGSID&gt;&quot;
          &#125;,
          &quot;recipient&quot;: &#123;
            &quot;id&quot;: &quot;&lt;IGID&gt;&quot;
          &#125;,
          &quot;timestamp&quot;: 1569262485349,
          &quot;message&quot;: &#123;
            &quot;mid&quot;: &quot;&lt;MESSAGE_ID&gt;&quot;,
            &quot;attachments&quot;:[
              &#123;
                  &quot;type&quot;:&quot;story_mention&quot;,
                  &quot;payload&quot;:&#123;
                     &quot;url&quot;:&quot;&lt;CDN_URL&gt;&quot;
                  &#125;
              &#125;
            ]
          &#125;
        &#125;
      ]
    &#125;
  ],
&#125;
```

## Example request to retrieve story mention via Conversation API

```json
GET &lt;MESSAGE_ID&gt;?fields=story

&#123;
  &quot;story&quot;: &#123;
    &quot;mention&quot;: &#123;
      &quot;link&quot;: &quot;&lt;CDN_URL&gt;&quot;,
      &quot;id&quot;: &quot;&lt;STORY_ID&gt;&quot;
    &#125;
  &#125;,
  &quot;id&quot;: &quot;&lt;MESSAGE_ID&gt;&quot;
&#125;
```

### Developer Support

* Use the  [Meta Status tool](https://metastatus.com) to check for the status and outages of Meta business products.
* Use the [Meta Developer Support tool](https://developers.facebook.com/support) to report bugs and view reported bugs, get help with Ads or Business Manager, and more.

