---
show: true
width: 6
date: 2026-10-02 00:00:10 -0400
---
<!-- Favorite projects; edit the list in _data/showcase.yml. -->
<div class="p-3">
    <h4 class="mb-2"><i class="fas fa-star"></i> Favorite Projects</h4>
    <ul class="list-unstyled mb-0">
        {% for p in site.data.showcase.favorite_projects %}
        <li class="py-2 {% unless forloop.first %}border-top border-gray{% endunless %}">
            <div class="font-weight-bold">{% if p.link %}<a class="text-body" href="{{ p.link }}"{% unless p.link == "#" %} target="_blank"{% endunless %}>{{ p.title }}</a>{% else %}{{ p.title }}{% endif %}</div>
            <div class="small text-muted">{{ p.description }}</div>
        </li>
        {% endfor %}
    </ul>
</div>
