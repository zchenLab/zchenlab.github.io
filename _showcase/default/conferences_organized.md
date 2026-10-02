---
show: true
width: 6
date: 2026-10-02 00:00:20 -0400
---
<!-- Conferences and meetings organized; edit the list in _data/showcase.yml. -->
<div class="p-3">
    <h4 class="mb-2"><i class="fas fa-calendar-check"></i> Conferences and Meetings Organized</h4>
    <ul class="list-unstyled mb-0">
        {% for c in site.data.showcase.conferences_organized %}
        <li class="py-2 {% unless forloop.first %}border-top border-gray{% endunless %}">
            <div>{{ c.name }}</div>
            <div class="small text-muted">
                {{ c.role }}{% if c.year %} &middot; {{ c.year }}{% endif %}
                {% if c.program_book %} &middot; <a href="{{ c.program_book }}"{% unless c.program_book == "#" %} target="_blank"{% endunless %}><i class="fas fa-book"></i> Program book</a>{% endif %}
            </div>
        </li>
        {% endfor %}
    </ul>
</div>
