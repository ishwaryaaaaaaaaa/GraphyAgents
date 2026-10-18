### Handoff demo transcript

```
[  2.7s advisor] started (pid 13040), connected to its own MCP server
[  2.3s intake ] started (pid 23568), connected to its own MCP server
[  2.3s intake ] hears: 'I used to eat meat, I love fried chicken and paneer wrap'
[  2.5s intake ] hears (day 10): 'I turned vegetarian'
[  2.5s intake ] handed h5 to the advisor: 'fried chicken or chana chaat?'
[  4.2s advisor] claimed h5 from intake: 'fried chicken or chana chaat?'
[  4.2s advisor] answers chana chaat  (reasons: you are vegetarian; rejected: {'fried_chicken': 'you are vegetarian'})
[  2.7s intake ] h5 answered by advisor: chana chaat (decision d6)
[  2.7s intake ] hears (day 12): 'I hate paneer wrap'  (a mistake: it was a friend's message)
[  2.8s intake ] handed h9 to the advisor: 'paneer wrap or chana chaat?'
[  4.5s advisor] claimed h9 from intake: 'paneer wrap or chana chaat?'
[  4.5s advisor] answers chana chaat  (reasons: you dislike it; rejected: {'paneer_wrap': 'you dislike it'})
[  3.0s intake ] h9 answered by advisor: chana chaat (decision d10)
[  3.0s intake ] hears (day 14): 'that was wrong about paneer wrap'  -> retracts it
[  3.0s intake ] retraction also dropped: ['avoid_paneer_wrap_orders']
[  3.0s intake ] handed h11 to the advisor: 'paneer wrap or chana chaat?'
[  4.8s advisor] claimed h11 from intake: 'paneer wrap or chana chaat?'
[  4.8s advisor] answers paneer wrap  (reasons: you like it; rejected: none)
[  3.3s intake ] h11 answered by advisor: paneer wrap (decision d12)
[  3.3s intake ] done
[  5.1s advisor] done (3 handoffs)
```
