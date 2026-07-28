# Stories



Represents a collection of story [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects on an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user).

## Creating &#123;#create&#125;

For creating Stories Media, refer to the [Instagram User Media](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media) documentation.

## Reading &#123;#read&#125;

### Getting Stories &#123;#stories&#125;

`GET /&#123;ig-user-id&#125;/stories`

Returns a list of story [IG Media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media) objects on an [IG User](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user).

#### Limitations

* Responses will not include Live Video stories.
* Stories are only available for 24 hours.
* New stories created when a user reshares a story will not be returned.
* Only one caption will be returned per Instagram story, even if more than one caption exists.

#### Permissions

A Facebook User [access token](https://developers.facebook.com/documentation/instagram-platform/overview#authentication) with the following permissions:

- `instagram_basic`
- `pages_read_engagement`

If the token is from a User whose **Page role was granted via the Business Manager**, one of the following permissions is also required:

- `ads_management`
- `ads_read`

#### Sample Request

```
GET graph.facebook.com
  /17841405822304914/stories
```

#### Sample Response

```
&#123;
  &quot;data&quot;: [
    &#123;
      &quot;id&quot;: &quot;17861937508009798&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17862253585030136&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17856428680064034&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17862537148046301&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17852121721080875&quot;
    &#125;,
    &#123;
      &quot;id&quot;: &quot;17862694123018235&quot;
    &#125;
  ]
&#125;
```

## Updating &#123;#update&#125;

This operation is not supported.

## Deleting &#123;#delete&#125;

This operation is not supported.
