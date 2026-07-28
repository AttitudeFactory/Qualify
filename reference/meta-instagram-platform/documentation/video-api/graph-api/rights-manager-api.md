# Rights Manager API



The Rights Manager API enables publishers to claim copyright ownership for videos and manage copyright matching rules with two new endpoints: the `video_copyright_rule` endpoint and `video_copyright` endpoint.

### Permissions
To use this API, you&#039;ll need to [apply for access](https://www.facebook.com/rights_manager/apply) to the Rights Manager tool (you must be signed in to Facebook to use this tool).
You can read more and learn about Rights Manager in [rightsmanager.fb.com](https://rightsmanager.fb.com).

## Copyrighting Video &#123;#copyrightvideo&#125;

The Rights Manager API can only be applied to videos on pages.  All pages need to go through the enrollment process in order to be eligible to use the API.  
Before you can copyright video you should create video content on a Facebook __Page__. This can be done through the Video Upload API or Live Video API.

### For Videos, the steps are:

1. Upload a video to Facebook and obtain video id.  
2. Use Rights Manager API to copyright the video.

### For Live Videos, the steps are:

1. Create a live_video object and obtain live video id.  
2. Use Rights Manager API to copyright the live video.  
3. Start streaming using your streaming software.

### Reference Only
If the video should be used __only__ as a reference video, and __not__ for consumption and distribution on Facebook, the video should be uploaded using the [&#039;reference_only&#039;](https://developers.facebook.com/docs/graph-api/reference/video) param, and the Rights Manager API needs to be called using the [`is_reference_video`](https://developers.facebook.com/docs/graph-api/reference/video-copyright#Creating) param.
When streaming, just make sure you call Rights Manager with &#039;is_reference_video&#039; before starting to stream.
The video or live video will not appear in your Video Library, and will only be visible to the Admin, in the Reference Files section of the Rights Manager tool.

## Understanding the `video_copyright_rule` and `video_copyright` Endpoints &#123;#differences&#125;

* `video_copyright_rule` endpoint: This endpoint allows you to create a copyright rule. For example, you can determine under what kind of condition a copyright report should be triggered and what kind of action should be taken.

* `video_copyright` endpoint: You can use this endpoint to copyright a specific video. You can also specify copyright ownership and apply a copyright rule here.

## The `video_copyright_rule` Endpoint &#123;#videocopyrightrule&#125;

The [`video_copyright_rule` endpoint](https://developers.facebook.com/docs/graph-api/reference/video-copyright-rule) allows you to create copyright rules that determine which actions to take on a video that matches these rules.  For example, you as a rights owner can create a copyright rule that allows usage of your video for less than 3 minutes.

There are several types of conditions:

* `GEO`: Determines if the video is available in a certain location.  For example, if a video can be viewed in the UK, and the geo condition is &#039;UK and US&#039;, then the video meets the condition.
* `OVERLAP_DURATION`: Determines how long the match occurs (greater or less than 2 or 3 minutes for example)
* `MATCH_OVERLAP_PERCENTAGE`: Determines what percentage of the matching video matches (greater or less than 20% of the matching video for example)
* `REFERENCE_OVERLAP_PERCENTAGE`: Determines what percentage of your reference file matches (greater or less than 50% for example)
* `MONITORING_TYPE`: Determines if the video, audio, or both match
* `PUBLISHER_TYPE`: Whether the matched video is owned by a Page, Profile, or either one.
* `PRIVACY`: Determines whether the matching video was public or non-public, or either. Non-public videos have a limited audience. For example, a video that is visible to a person&#039;s friends or to a group is non-public.

There are four available action types:

* `TRACK`: This action allows you to keep track of the matched video, without taking any action on it. In the future, you will also be able to see insights on the matched video.
* `MONETIZE`: This action allows you to share in the ad revenue that a video generates. It requires that you have set up Payments, which you can do from the Rights Manager section of your Page Settings.
* `BLOCK`: Blocking a video means it will not be visible in any geos in which you own it
* `MANUAL_REVIEW`: This action will send the match to the Manual Review section of Rights Manager, so that you may manually apply an action on the matched video. Matches in your manual review section will expire in 30 days.

## Creating a Copyright Rule &#123;#create&#125;

You can create a copyright rule by making a POST request to the `video_copyright_rules` edge at the following path: [`POST/&#123;pageid&#125;/video_copyright_rules`](https://developers.facebook.com/docs/graph-api/reference/video-copyright-rule#Creating).

```
curl \
-X POST \
&#039;https://graph.facebook.com/v2.6/405152342992687/video_copyright_rules&#039; \
 -F &#039;access_token=XXXXXXXX&#039; \
 -F &#039;name=&quot;testrule&quot;&#039; \
 -F &#039;condition_groups=[&#123;action:&quot;MANUAL_REVIEW&quot;,conditions:[&#123;type:&quot;MONITORING_TYPE&quot;,operator:&quot;IS&quot;,value:&quot;VIDEO_ONLY&quot;&#125;,&#123;type:&quot;OVERLAP_DURATION&quot;,operator:&quot;LESS_THAN&quot;,value:120000&#125;,&#123;type:&quot;GEO&quot;,operator:&quot;IN_SET&quot;,value:[&quot;AR&quot;,&quot;AU&quot;]&#125;]&#125;]&#039;
```

## Reading a Copyright Rule &#123;#read&#125;

Issue a [`GET /video_copyright_rule_id request`](d) to get more information about the copyright rule.

Note in this example that `576407315867188` is the copyright rule ID.

```
curl \
-X GET \
&#039;https://graph.facebook.com/v2.6/576407315867188?&amp;access_token=XXXXXXXX&#039; \
```

## Deleting a Copyright Rule &#123;#delete&#125;

You can delete a live video by making a [`DELETE /video_copyright_rule_id` request](https://developers.facebook.com/docs/graph-api/reference/video-copyright-rule#Deleting).

## The `video_copyright` Endpoint &#123;#videocopyright&#125;

The `video_copyright` endpoint allows you to specify which video you want to copyright.  From this endpoint, you can whitelist other pages or users to use the reference video.  For example, if you have 3 pages and want to copyright a certain video to be able to play on all of your pages, you can specify those pages in the whitelist.

## Creating a `video_copyright` Endpoint &#123;#creatingvideocopyright&#125;

You can make a `POST` request to the [`video_copyrights` edge](https://developers.facebook.com/docs/graph-api/reference/video-copyright#Creating) from the following paths: `/&#123;page_id&#125;/video_copyrights`

Note in this example that `576425449198708` is the video ID representing the video to be copyrighted.

```
curl \
-X POST \
&#039;https://graph.facebook.com/v2.6/405152342992687/video_copyrights&#039; \
-F  &#039;access_token=XXXXXXXX&#039; \
-F  &#039;copyright_content_id=576425449198708&#039; \
-F  &#039;is_reference_video=true&#039; \
-F  &#039;monitoring_type=VIDEO_ONLY&#039; \
-F  &#039;rule_id=576407315867188&#039; \
-F  &#039;whitelisted_ids=[139577256378818]&#039; \
-F  &#039;ownership_countries=[“us”,”ca”]&#039; \
Return values: Video copyright id.
&#123;&quot;id&quot;:&quot;576425925865327&quot;&#125;
```

For any given video, you can query the &#039;copyright&#039; field to obtain more information about the `video_copyright` node.

```
curl \
-X GET \
&#039;https://graph.facebook.com/v2.6/576407315867188?fields=copyright&amp;access_token=XXXXXXXX&#039; \
```

Update, Read, and Delete capabilities are also available for the `video_copyright` endpoint.  For more information, please refer to the [video copyright endpoint documentation](https://developers.facebook.com/docs/graph-api/reference/video-copyright).
