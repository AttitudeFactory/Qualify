# Embed an Instagram Post



You can query the Instagram oEmbed endpoint to get an Instagram post’s embed HTML and basic metadata in order to display the post in another website or app. Supports photo, video, Reel, and Feed posts.

Visit the [Instagram Help Center](https://help.instagram.com/620154495870484) to learn how to get the embed code from a public Instagram post or profile.

### Common uses

* Embed a post in a blog
* Embed a post in a website
* Render a post in a content management system
* Render a post in a messaging app

## Requirements

#### Base URL

All endpoints can be accessed via the `graph.facebook.com` host.

#### Endpoints

- [`GET /instagram_oembed`](https://developers.facebook.com/docs/graph-api/reference/instagram-oembed)

### Limitations

* The Instagram oEmbed endpoint is **only** meant to be used for embedding Instagram content in websites and apps. It is not to be used for any other purpose. **Using metadata and page, post, or video content (or their derivations) from the endpoint for any purpose other than providing a front-end view of the page, post, or video is strictly prohibited**. This prohibition encompasses consuming, manipulating, extracting, or persisting the metadata and content, including but not limited to deriving information about pages, posts, and videos from the metadata for analytics purposes.
* Posts on private, inactive, and age-restricted Instagram accounts are not supported.
* Accounts that have [disabled **Embeds**](https://help.instagram.com/252460186989212/) are not supported.
* Stories are not supported.
* Shadow DOM is not supported.

### Rate limits

You can make up to 1,000 requests every hour.

## Get an embed HTML

You can get an embed HTML programmatically or [in the Instagram app.](https://developers.facebook.com/documentation/instagram-platform/embed-button)

To programmatically get an Instagram post&#039;s embed HTML, send a request to:

```json
GET /instagram_oembed?url=&lt;URL_OF_THE_POST&gt;
```

Replace `&lt;URL_OF_THE_POST&gt;` with the [URL](#url-formats) of the Instagram post that you want to query.

Upon success, the API will respond with a JSON object containing the post&#039;s embed HTML and additional data. The embed HTML will be assigned to the `html` property.

Refer to the [Instagram oEmbed reference](https://developers.facebook.com/docs/graph-api/reference/instagram-oembed) for a list of [query string parameters](https://developers.facebook.com/docs/graph-api/reference/instagram-oembed#parameters) you can include to augment the request. You may also include the `fields` query string parameter to specify which [fields](https://developers.facebook.com/docs/graph-api/reference/instagram-oembed#fields) you want returned. If omitted, all default Fields will be included in the response.

### Sample requests

```curl
curl -X GET \
  &quot;https://graph.facebook.com/v25.0/instagram_oembed?url=https://www.instagram.com/p/fA9uwTtkSN/&quot;
```

```curl
curl -i -X GET \
     &quot;https://graph.facebook.com/v25.0/instagram_oembed?url=https%3A%2F%2Fwww.instagram.com%2Fp%2FfA9uwTtkSN&quot;
```

### Sample Response

Some values truncated with an ellipsis (`...`) for readability.

```json
&#123;
  &quot;version&quot;: &quot;1.0&quot;,
  &quot;provider_name&quot;: &quot;Instagram&quot;,
  &quot;provider_url&quot;: &quot;https://www.instagram.com/&quot;,
  &quot;type&quot;: &quot;rich&quot;,
  &quot;width&quot;: 658,
  &quot;html&quot;: &quot;&lt;blockquote class=\&quot;instagram-media\&quot; data-instgrm-ca...&quot;,
&#125;
```

### URL Formats

The `url` query string parameter accepts the following URL formats:

* Single image and carousel posts: `https://www.instagram.com/p/&#123;media-shortcode&#125;/`
* Videos/Reels: `https://www.instagram.com/reel/&#123;media-shortcode&#125;/`
* Profiles: `https://www.instagram.com/&#123;username&#125;`

### Embed JS

The embed HTML contains a reference to the Instagram [embed.js](https://www.instagram.com/embed.js) JavaScript library. When the library loads, it scans the page for the post HTML and generates the fully rendered post. If you want to load the library separately, include the `omitscript=true` query string parameter in your request. To manually initialize the embed HTML, call the `instgrm.Embeds.process()` function after loading the library.

### Post Size

The embedded post is responsive and will adapt to the size of its container. This means that the height will vary depending on the container width and the length of the caption. You can set the maximum width by including the `maxwidth` query string parameter in your request.
