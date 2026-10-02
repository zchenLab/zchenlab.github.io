---
show: true
width: 6
date: 2026-10-02 00:00:05 -0400
---
<!-- Media coverage; edit the list in _data/showcase.yml. -->
<div class="p-3">
    <h4 class="mb-2"><i class="fas fa-newspaper"></i> Media Coverage</h4>
    <ul class="list-unstyled mb-0">
        {% for m in site.data.showcase.media_coverage %}
        <li class="py-2 {% unless forloop.first %}border-top border-gray{% endunless %}">
            <div>{% if m.link %}<a class="text-body" href="{{ m.link }}"{% unless m.link == "#" %} target="_blank"{% endunless %}>{{ m.title }}</a>{% else %}{{ m.title }}{% endif %}</div>
            <div class="small text-muted"><i>{{ m.outlet }}</i>{% if m.type %} &middot; {{ m.type }}{% endif %}{% if m.date %} &middot; {{ m.date }}{% endif %}{% if m.link %} &middot; <a href="{{ m.link }}"{% unless m.link == "#" %} target="_blank"{% endunless %}><i class="fas fa-external-link-alt"></i> Read</a>{% endif %}</div>
        </li>
        {% endfor %}
    </ul>
</div>
