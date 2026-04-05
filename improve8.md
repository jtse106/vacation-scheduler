X to do list. read in entirety first. place X next to each one when complete -- these are already done and don't need to be completed.

X when logged in as a user and you select dates to edit, a new line pops up, see Screenshot 2026-04-04 154524. it's outlined in red circle. this should appear in the yellow highlighted area instead. delete the orange highlighted text.


X adjust the sub-pages (request history, holiday rotation, legacy calendars, etc) so they look like the main calendar page with respect to the header, panels, color scheme, layout, css, etc. see screenshot Screenshot 2026-04-04 15452422. the red circle shows the header for the main calendar, all the sub-pages need similar styling. the gree circle shows how the left panel spacing looks on the main scheduler site, the sub pages needs to look similar.

X when selecting dates as a user, instead of having a 'clear button' in order to deselect you should just click away from any of the dates (anywhere else on in the window).

X add a score to the easter egg that's based on time and efficiency. make a high score and say which user has gotten the high score. this should persist in the database so different sessions see the same high score.


X When I'm logged in as a user select a bunch of dates by clicking and dragging, it automatically deselects the dates when I'm done dragging. This is a new problem. It was working before as expected. I think it might have to do something with the feature where if you click away it will deselect the selected dates. But I still need to be able to click and drag and select the dates that I want. Then once those dates are selected then I could click away and they would deselect them. 

X Also once a day or several dates are selected it adds the Assign me or unassign me button which is fine. However the button is a little too big It actually is bigger than banner size that it's being added to and therefore it shifts the calendar dates down by just a little bit to make room for that button. The whole point is to keep it in line with the banner and not create any size changes when the button appears so dates don't shift. Every time the dates shift downward up back upward it's not smooth and jumpy and it looks unprofessional. So the button needs to be small enough to fit on that row without being so big that it causes any shifts in the layout size.

X add a random golden bar to the breakout game that turns the ball into 3 balls that spread out in different directions. now the paddle has to manage all 3 balls. each ball counts as a life.

X when you click the side panel options, Even if the right panel changes its size the left panel should still say the same size. It doesn't have to match the height of the right panel When you're in these sub pages. It should really just match the height of the web page like it does on the main calendar view.

X It doesn't need to say "Live Schedule"

X where it says "South Bay ED VL Schedule" on the main schedule page, the size of this banner should persist when going to the sub pages. meaning atht eh small mini calendar and left pane should go all the way to the top.

X I have added gmail secret token and refresh token, yet still running into problems with sending emails. see if you can troubleshoot this. tell me what's wrong and what i need to fix.

X don't need a "Open Standalone reset page" on the Login site.

X add a South Bay ED VL Schedule link to the Left lower pane that returns back to teh main schedule, this should be the top option.

X Don't allow additions to the schedule more than 1 year in advance. this applies to the AI assistant as well. make the bottor right error message say this if needed.

X add detailed logs stating all the messages and details for all the AI assisted scheduling and emailing including all the details, everything, don't spare any detail.

X if someone has a holiday request trade request from another doctor to them, put a message at the top of the screen (unobtrusively) when they login, that should catche their attention to let them know. then they click it and it takes them to the Holiday trades area where they can accept or reject it.

X put a authorized delegates link into the L lower card as its own separate setting.
X put a holiday trades link into the L lower card to make it its own separate setting.
X make a gear icon for the settings button top upper right.
X also put a settings link in the left lower card

X delete all the current VL calendar vacation requests. then sync the current calendar to the legacy calendars.

X make the waitlist visible (with order and timestamps -- unobtrusive timestamps) if you click the waitlist badge on any given date. this should be available for all users. and it should be editable for the admin. 

X make the gold bar in the easter egg breakout game more randomly placed, and make it truly gold colored instead of just yellow. make it look like a gold bar.

when you lose in the breakout game, it should flash game over across the screen

also, reset the high score to zero. and make the score countdown count down from 10000. and make your score go higher the longer you keep all 3 balls alive.

the gear looks wierd in the settings in upper right button. use playwright to look at it and fix it with a better gear icon.

there's a problem with the waitlist, if a User selects multiple dates and some of the dates Have all of their slots full But some of the selected dates are not completely filled, when you Click to assign yourself to these shifts. The dates that are completely filled should be put on the wait list but the dates that have openings that doctor should be assigned to those open slots. As it stands currently the Doctor is just assigned to the wait list across the entire selection even if a portion of the selection has open slots.

But there should be a way for the administrator to manually edit the holiday rotation schedule.

The legacy VL calendars are considered a truth as of April 4th 2026. There should be a button on the legacy VL calendar section to synchronize the current schedule to the legacy VL calendars. A copy of the current actual schedule should be saved into the database in case it needs to be restored at a later point. everything should be logged appropriately.